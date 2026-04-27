"""B-roll Planner — превращает Deepgram JSON в список items[] для Submagic.

Цель: дать пользователю автоматический «умный» режим монтажа, в котором:
  1) сегменты для B-roll выбираются из реальных пауз/предложений (Deepgram),
  2) визуальные промпты ИИ-ролика для B-roll генерируются LLM с жёстким
     запретом иностранной символики (флаги, военная форма, политики и т.п.),
  3) на выходе — items[] строго по схеме Submagic API:
       { "type": "ai-broll", "startTime": <sec>, "endTime": <sec>,
         "prompt": "<en text>", "layout": "cover" | "split-50-50" | "pip" }

Submagic API constraints (учтены в build):
  - длительность одного ai-broll ≤ 12 сек,
  - items не должны пересекаться,
  - prompt ≤ 2500 символов,
  - сортировка по startTime.

Ссылки:
  - https://docs.submagic.co/api-reference/create-project
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger("broll_planner")


# ──────────────────────────── параметры алгоритма ────────────────────────────

DENSITY_DIVIDER = {"low": 30.0, "medium": 15.0, "high": 9.0}

SEG_MIN_LEN = 3.0          # минимальная длина одной B-roll вставки (сек)
SEG_MAX_LEN = 10.0         # абсолютный максимум; Submagic-ограничение — 12 сек
CLIP_DURATION_DEFAULT = 5  # дефолтная максимальная длина вставки (пользовательский параметр)
CLIP_DURATION_MIN = 3      # нижний предел выбора пользователем
CLIP_DURATION_MAX = 10     # верхний предел выбора пользователем
SEG_GAP = 2.0              # минимум тишины/паузы между двумя B-roll
EDGE_PAD = 1.5             # запас от начала и конца видео
MIN_VIDEO_DURATION = 20.0  # < 20 сек — Smart-режим не применим
MAX_VIDEO_DURATION = 90.0  # > 90 сек — слишком длинно для Reels-монтажа
PROMPT_MAX_LEN = 2500      # лимит Submagic

TOPIC_LABELS = {
    "auto":    "general (определи по тексту сегмента)",
    "law":     "военное право, юридический процесс, призыв",
    "army":    "армейская служба, военная подготовка, военкомат",
    "medical": "военно-врачебная комиссия, медицинское освидетельствование, медкарты",
    "process": "административно-юридический процесс, документы, печати, суд",
    "general": "общая юридическая тематика для россиян",
}


@dataclass
class _Segment:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


# ───────────────────────────── публичный API ─────────────────────────────────

class BrollPlannerError(Exception):
    """Понятная ошибка для пользователя/SSE."""


async def plan_broll_items(
    deepgram_json: dict,
    *,
    density: str = "medium",
    clip_duration: int = CLIP_DURATION_DEFAULT,
    topic_hint: str = "auto",
    layout: str = "cover",
    extra_prompt: str = "",
    llm_model: str = "gemini-flash-latest",
    russia_only: bool = True,
) -> tuple[list[dict], dict]:
    """Возвращает (items, stats).

    items  — список объектов для Submagic create_project(items=...).
    stats  — { "broll_items_count", "video_duration_sec", "llm_model",
               "in_tokens", "out_tokens", "cost" } для сохранения в узле.

    clip_duration — максимальная длина одной B-roll вставки в секундах (3–10).
                    Меньшее значение даёт динамичный клиповый стиль.

    Бросает BrollPlannerError при некорректных входных данных.
    """
    if density not in DENSITY_DIVIDER:
        density = "medium"
    if layout not in {"cover", "split-50-50", "pip"}:
        layout = "cover"
    clip_duration = max(CLIP_DURATION_MIN, min(CLIP_DURATION_MAX, int(clip_duration)))

    raw_segments = _extract_segments(deepgram_json)
    if not raw_segments:
        raise BrollPlannerError("Deepgram JSON не содержит распознанных сегментов")

    total = raw_segments[-1].end
    if total < MIN_VIDEO_DURATION:
        raise BrollPlannerError(
            f"Длительность видео {total:.1f}с меньше {MIN_VIDEO_DURATION:.0f}с — "
            "Smart-режим неприменим (используйте Auto)"
        )
    if total > MAX_VIDEO_DURATION:
        logger.warning(f"Smart broll: длинное видео {total:.1f}с (>{MAX_VIDEO_DURATION:.0f}с), продолжаем")

    target_count = max(1, round(total / DENSITY_DIVIDER[density]))
    picked = _pick_segments(raw_segments, target_count, total, max_clip_sec=clip_duration)

    if not picked:
        raise BrollPlannerError("Не удалось подобрать сегменты для B-roll")

    prompts, llm_stats = await _generate_prompts(
        picked,
        topic_hint=topic_hint,
        extra_prompt=extra_prompt,
        llm_model=llm_model,
        russia_only=russia_only,
    )

    items: list[dict] = []
    for seg, prompt in zip(picked, prompts):
        if not prompt:
            continue
        prompt = prompt.strip()[:PROMPT_MAX_LEN]
        items.append({
            "type": "ai-broll",
            "startTime": round(seg.start, 2),
            "endTime": round(seg.end, 2),
            "prompt": prompt,
            "layout": layout,
        })

    items.sort(key=lambda it: it["startTime"])

    stats = {
        "broll_items_count": len(items),
        "clip_duration": clip_duration,
        "video_duration_sec": round(total, 2),
        "llm_model": llm_stats.get("model", llm_model),
        "in_tokens": llm_stats.get("in_tokens", 0),
        "out_tokens": llm_stats.get("out_tokens", 0),
        "cost": round(llm_stats.get("cost", 0.0), 6),
    }
    return items, stats


# ────────────────────────────── сегментация ──────────────────────────────────

def _extract_segments(dg: dict) -> list[_Segment]:
    """Парсит Deepgram-ответ в плоский список (start, end, text) сегментов.

    Приоритет источников: paragraphs.sentences -> utterances -> grouped words.
    """
    results = (dg or {}).get("results") or {}
    channels = results.get("channels") or []
    alternatives = (channels[0].get("alternatives") if channels else []) or []
    alt = alternatives[0] if alternatives else {}

    paragraphs_root = alt.get("paragraphs") or {}
    paragraphs = paragraphs_root.get("paragraphs") or []
    segments: list[_Segment] = []
    for p in paragraphs:
        for s in (p.get("sentences") or []):
            text = (s.get("text") or "").strip()
            if not text:
                continue
            start = float(s.get("start", 0))
            end = float(s.get("end", 0))
            if end > start:
                segments.append(_Segment(start, end, text))

    if segments:
        return segments

    for u in (results.get("utterances") or []):
        text = (u.get("transcript") or "").strip()
        if not text:
            continue
        start = float(u.get("start", 0))
        end = float(u.get("end", 0))
        if end > start:
            segments.append(_Segment(start, end, text))

    if segments:
        return segments

    words = alt.get("words") or []
    if not words:
        return []
    chunk: list[dict] = []
    for w in words:
        chunk.append(w)
        if len(chunk) >= 8:
            text = " ".join((x.get("punctuated_word") or x.get("word") or "") for x in chunk).strip()
            segments.append(_Segment(float(chunk[0]["start"]), float(chunk[-1]["end"]), text))
            chunk = []
    if chunk:
        text = " ".join((x.get("punctuated_word") or x.get("word") or "") for x in chunk).strip()
        segments.append(_Segment(float(chunk[0]["start"]), float(chunk[-1]["end"]), text))
    return segments


def _pick_segments(
    segments: list[_Segment],
    target: int,
    total: float,
    max_clip_sec: int = CLIP_DURATION_DEFAULT,
) -> list[_Segment]:
    """Отбирает до `target` сегментов под критерии длины, отступов и непересечения.

    Алгоритм (детерминированный):
      1) Готовим кандидатов длиной [SEG_MIN_LEN..max_clip_sec]. Длинные обрезаем,
         короткие склеиваем со следующим.
      2) Сортируем кандидатов: сначала те, чья длина ≤ max_clip_sec × 1.1 (близко
         к желаемой), затем остальные — предпочитаем вставки нужной длины,
         а не максимально длинные.
      3) Жадно берём, пропуская пересечения и нарушения EDGE_PAD/SEG_GAP.
      4) Возвращаем выбранные в порядке startTime.
    """
    candidates = _build_candidates(segments, total, max_clip_sec=max_clip_sec)

    target_len = float(max_clip_sec)
    # Ранжируем: минимизируем отклонение от желаемой длины clip_duration
    candidates_ranked = sorted(candidates, key=lambda s: abs(s.duration - target_len))
    picked: list[_Segment] = []
    for cand in candidates_ranked:
        if len(picked) >= target:
            break
        if any(_overlap_or_too_close(cand, p) for p in picked):
            continue
        picked.append(cand)
    picked.sort(key=lambda s: s.start)
    return picked


def _build_candidates(
    segments: list[_Segment],
    total: float,
    max_clip_sec: int = CLIP_DURATION_DEFAULT,
) -> list[_Segment]:
    out: list[_Segment] = []
    i = 0
    while i < len(segments):
        s = segments[i]
        start, end, text = s.start, s.end, s.text
        # Не берём края
        if start < EDGE_PAD:
            start = EDGE_PAD
        if end > total - EDGE_PAD:
            end = total - EDGE_PAD
        if end - start < SEG_MIN_LEN:
            # склейка с будущими, пока не наберём минимум
            j = i + 1
            while j < len(segments) and (end - start) < SEG_MIN_LEN:
                end = min(segments[j].end, total - EDGE_PAD)
                text = (text + " " + segments[j].text).strip()
                j += 1
            i = j
        else:
            i += 1

        if end - start < SEG_MIN_LEN:
            continue
        # обрезаем по пользовательскому лимиту (не выше абсолютного максимума API)
        effective_max = min(max_clip_sec, SEG_MAX_LEN)
        if end - start > effective_max:
            end = start + effective_max
        out.append(_Segment(round(start, 2), round(end, 2), text))
    return out


def _overlap_or_too_close(a: _Segment, b: _Segment) -> bool:
    if a.start >= b.end:
        return (a.start - b.end) < SEG_GAP
    if b.start >= a.end:
        return (b.start - a.end) < SEG_GAP
    return True  # настоящее пересечение


# ─────────────────────────── генерация промптов ──────────────────────────────

async def _generate_prompts(
    segs: list[_Segment],
    *,
    topic_hint: str,
    extra_prompt: str,
    llm_model: str,
    russia_only: bool,
) -> tuple[list[str], dict]:
    """Один батч-вызов LLM возвращает массив промптов (по одному на сегмент).

    Сейчас поддерживается только Gemini (быстро, дёшево). Для Claude — fallback
    на Gemini Flash, чтобы не тащить ещё один SDK-путь в этом модуле.
    """
    if not segs:
        return [], {"model": llm_model, "in_tokens": 0, "out_tokens": 0, "cost": 0.0}

    topic_label = TOPIC_LABELS.get(topic_hint, TOPIC_LABELS["auto"])
    russia_clause = (
        "STRICT RULE: never depict flags, coats of arms, military uniforms, "
        "license plates or written signs of foreign countries. Russian symbolism "
        "is allowed only when the segment text explicitly justifies it. Prefer "
        "neutral footage (documents, hands signing, archives, generic offices, "
        "Russian nature)."
    ) if russia_only else (
        "Prefer culturally neutral footage; avoid politically charged imagery."
    )

    extra_clause = f"\nUser extra notes (consider but never break the strict rule): {extra_prompt.strip()[:300]}" if extra_prompt else ""

    items_input = [
        {"index": i, "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
        for i, s in enumerate(segs)
    ]

    system_prompt = (
        "Ты режиссёр короткометражного видео для русскоязычной юридической "
        f"аудитории (тема: {topic_label}). Для каждого сегмента предложи короткий "
        "(≤200 символов) англоязычный prompt для AI-генератора B-roll-видео. "
        "Промпт должен быть конкретным, визуальным и подходить к смыслу фразы.\n"
        f"{russia_clause}{extra_clause}\n\n"
        "Запрещено: американские/европейские флаги и символика, лица западных "
        "политиков, иностранная военная форма, надписи на иностранных языках на "
        "вывесках, NATO/EU/USA-айдентика.\n\n"
        "Верни ТОЛЬКО JSON-массив вида: "
        '[{"index":0,"prompt":"..."},{"index":1,"prompt":"..."}]. '
        "Никаких пояснений вне JSON."
    )

    user_payload = json.dumps({"segments": items_input}, ensure_ascii=False)

    # Нормализуем модель: если просили Claude — для broll берём Gemini Flash,
    # чтобы не нагружать дорогую модель и не плодить сетевые SDK-зависимости.
    effective_model = llm_model
    if (effective_model or "").startswith("claude-"):
        effective_model = "gemini-flash-latest"

    try:
        prompts_by_idx, in_tokens, out_tokens = await _call_gemini_json(
            effective_model, system_prompt, user_payload
        )
    except Exception as e:
        logger.error(f"broll planner LLM error: {e}; falling back to neutral generic prompts")
        # Fallback: всё равно вернём что-то осмысленное и безопасное
        fallback = "neutral office documents, paperwork stacks, hands flipping pages, soft warm light, cinematic"
        return [fallback] * len(segs), {
            "model": effective_model, "in_tokens": 0, "out_tokens": 0, "cost": 0.0
        }

    prompts: list[str] = []
    for i, _ in enumerate(segs):
        p = prompts_by_idx.get(i, "").strip()
        if not p:
            p = "neutral close-up of hands signing a document, soft indoor light, cinematic"
        prompts.append(p)

    cost = _gemini_cost(effective_model, in_tokens, out_tokens)
    return prompts, {
        "model": effective_model,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "cost": cost,
    }


async def _call_gemini_json(model_name: str, system: str, user: str) -> tuple[dict[int, str], int, int]:
    if not getattr(settings, "gemini_api_key", ""):
        raise RuntimeError("GEMINI_API_KEY не установлен")
    # Ленивый импорт: SDK тяжёлый и не нужен в тестах, где функция мокается.
    import google.generativeai as genai
    genai.configure(api_key=settings.gemini_api_key)

    model = genai.GenerativeModel(model_name, system_instruction=system)
    response = await model.generate_content_async(
        user,
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.6,
        ),
    )

    text = (getattr(response, "text", "") or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # иногда модель возвращает {"items":[...]}; пробуем распарсить мягко
        match = re.search(r"\[.*\]", text, flags=re.S)
        data = json.loads(match.group(0)) if match else []

    if isinstance(data, dict):
        data = data.get("items") or data.get("prompts") or []

    out: dict[int, str] = {}
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            idx = row.get("index")
            prompt = row.get("prompt") or ""
            if isinstance(idx, int):
                out[idx] = str(prompt)

    usage = getattr(response, "usage_metadata", None)
    in_tokens = getattr(usage, "prompt_token_count", 0) or 0
    out_tokens = getattr(usage, "candidates_token_count", 0) or 0
    return out, int(in_tokens), int(out_tokens)


def _gemini_cost(model_name: str, in_tokens: int, out_tokens: int) -> float:
    """Ленивая оценка стоимости через прайс из ai_models.json."""
    try:
        from app.services.gemini_service import calculate_cost as _cost
        in_c, out_c = _cost(in_tokens, out_tokens, model_name)
        return float(in_c) + float(out_c)
    except Exception:
        return 0.0
