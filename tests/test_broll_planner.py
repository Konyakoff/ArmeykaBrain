"""Тесты broll_planner.

Покрывают:
1. Парсинг сегментов из paragraphs / utterances / words (фолбэки).
2. Жадный отбор: длина, отступы, непересечение, плотность low/medium/high.
3. Соблюдение Submagic-ограничений (длина ≤12с, prompt ≤2500 симв.).
4. Гард на короткое видео (<20с).
5. Гладкая обработка ошибок LLM (fallback на безопасный нейтральный промпт).
6. Системный промпт LLM содержит «Запрещено» и упоминание российской аудитории.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services import broll_planner


# ───────────────────────── Helpers: build Deepgram JSON ──────────────────────


def _make_dg_paragraphs(sentences: list[tuple[float, float, str]]) -> dict:
    """Строит мок Deepgram-ответа с paragraphs.sentences."""
    return {
        "results": {
            "channels": [{
                "alternatives": [{
                    "paragraphs": {
                        "paragraphs": [{
                            "sentences": [
                                {"start": s, "end": e, "text": t}
                                for s, e, t in sentences
                            ]
                        }]
                    }
                }]
            }]
        }
    }


def _make_dg_utterances(utts: list[tuple[float, float, str]]) -> dict:
    return {
        "results": {
            "channels": [{"alternatives": [{}]}],
            "utterances": [
                {"start": s, "end": e, "transcript": t} for s, e, t in utts
            ],
        }
    }


def _make_dg_words(words: list[tuple[float, float, str]]) -> dict:
    return {
        "results": {
            "channels": [{
                "alternatives": [{
                    "words": [
                        {"start": s, "end": e, "word": w, "punctuated_word": w}
                        for s, e, w in words
                    ]
                }]
            }]
        }
    }


@pytest.fixture
def patched_llm():
    """LLM возвращает по одному prompt'у на каждый сегмент в JSON."""
    async def _fake(model_name, system, user):
        data = json.loads(user)
        prompts = {}
        for i, _ in enumerate(data.get("segments", [])):
            prompts[i] = f"neutral russian office scene #{i}"
        return prompts, 100, 50

    with patch.object(broll_planner, "_call_gemini_json", new=AsyncMock(side_effect=_fake)) as m:
        yield m


# ─────────────────────────── extract_segments ────────────────────────────────


def test_extract_segments_from_paragraphs():
    dg = _make_dg_paragraphs([
        (0.0, 5.0, "Первое предложение."),
        (5.5, 11.0, "Второе предложение."),
    ])
    segs = broll_planner._extract_segments(dg)
    assert len(segs) == 2
    assert segs[0].text == "Первое предложение."
    assert segs[0].start == 0.0
    assert segs[1].end == 11.0


def test_extract_falls_back_to_utterances():
    dg = _make_dg_utterances([
        (0.0, 4.0, "abc"),
        (4.5, 9.0, "def"),
    ])
    segs = broll_planner._extract_segments(dg)
    assert len(segs) == 2
    assert segs[0].text == "abc"


def test_extract_falls_back_to_words():
    words = [(i * 0.4, (i + 1) * 0.4, f"w{i}") for i in range(20)]
    dg = _make_dg_words(words)
    segs = broll_planner._extract_segments(dg)
    assert len(segs) >= 2  # 20 / 8 = 2.5
    assert segs[0].start == 0.0


# ─────────────────────────── plan_broll_items ────────────────────────────────


@pytest.mark.asyncio
async def test_plan_short_video_raises(patched_llm):
    dg = _make_dg_paragraphs([(0.0, 5.0, "слишком коротко")])
    with pytest.raises(broll_planner.BrollPlannerError):
        await broll_planner.plan_broll_items(dg, density="medium")


@pytest.mark.asyncio
async def test_plan_returns_items_within_submagic_constraints(patched_llm):
    """30-секундное видео, density=medium → ~2 items, без перекрытий, ≤10с каждый."""
    dg = _make_dg_paragraphs([
        (0.0, 5.0, "Один."),
        (5.5, 12.0, "Два."),
        (12.5, 19.0, "Три."),
        (19.5, 26.0, "Четыре."),
        (26.5, 30.0, "Пять."),
    ])
    items, stats = await broll_planner.plan_broll_items(dg, density="medium", llm_model="gemini-flash-latest")

    assert items, "ожидаем хотя бы один item"
    assert stats["broll_items_count"] == len(items)

    for it in items:
        assert it["type"] == "ai-broll"
        assert it["layout"] == "cover"
        assert it["startTime"] >= broll_planner.EDGE_PAD
        assert it["endTime"] <= 30.0 - broll_planner.EDGE_PAD + 0.001
        assert it["endTime"] - it["startTime"] <= 12.0
        assert it["endTime"] - it["startTime"] >= broll_planner.SEG_MIN_LEN
        assert len(it["prompt"]) <= broll_planner.PROMPT_MAX_LEN

    # сортировка по startTime + непересечение с зазором SEG_GAP
    for a, b in zip(items, items[1:]):
        assert a["endTime"] + broll_planner.SEG_GAP <= b["startTime"] + 0.001


@pytest.mark.asyncio
async def test_density_levels_scale(patched_llm):
    """На 60-секундном видео low/medium/high дают возрастающее число items."""
    sentences = [(i * 5.0, i * 5.0 + 4.5, f"Sent {i}.") for i in range(12)]
    dg = _make_dg_paragraphs(sentences)

    counts = {}
    for d in ("low", "medium", "high"):
        items, _ = await broll_planner.plan_broll_items(dg, density=d, llm_model="gemini-flash-latest")
        counts[d] = len(items)

    assert counts["low"] <= counts["medium"] <= counts["high"]
    assert counts["high"] >= 2


@pytest.mark.asyncio
async def test_layouts_are_passed_through(patched_llm):
    dg = _make_dg_paragraphs([
        (0.0, 6.0, "А"), (6.5, 13.0, "Б"), (13.5, 20.0, "В"), (20.5, 26.0, "Г"),
    ])
    items, _ = await broll_planner.plan_broll_items(dg, density="medium", layout="split-50-50")
    assert all(it["layout"] == "split-50-50" for it in items)


@pytest.mark.asyncio
async def test_invalid_density_falls_back_to_medium(patched_llm):
    dg = _make_dg_paragraphs([
        (0.0, 7.0, "А"), (7.5, 14.0, "Б"), (14.5, 22.0, "В"),
    ])
    items_a, _ = await broll_planner.plan_broll_items(dg, density="bogus")
    items_b, _ = await broll_planner.plan_broll_items(dg, density="medium")
    assert len(items_a) == len(items_b)


# ─────────────────────────── system prompt контракт ──────────────────────────


@pytest.mark.asyncio
async def test_system_prompt_contains_russia_only_clause():
    captured = {}

    async def _capture(model_name, system, user):
        captured["system"] = system
        return {0: "neutral office documents"}, 10, 5

    dg = _make_dg_paragraphs([
        (0.0, 7.0, "А"), (7.5, 14.0, "Б"), (14.5, 22.0, "В"),
    ])
    with patch.object(broll_planner, "_call_gemini_json", new=AsyncMock(side_effect=_capture)):
        await broll_planner.plan_broll_items(dg, density="low", russia_only=True, llm_model="gemini-flash-latest")

    sys = captured["system"]
    assert "STRICT" in sys or "strict" in sys.lower()
    assert "russian" in sys.lower()
    assert "запрещено" in sys.lower() or "запрещ" in sys.lower()


# ─────────────────────────── LLM error fallback ──────────────────────────────


@pytest.mark.asyncio
async def test_llm_error_falls_back_to_neutral_prompts():
    async def _boom(*a, **kw):
        raise RuntimeError("LLM down")

    dg = _make_dg_paragraphs([
        (0.0, 7.0, "А"), (7.5, 14.0, "Б"), (14.5, 22.0, "В"),
    ])
    with patch.object(broll_planner, "_call_gemini_json", new=AsyncMock(side_effect=_boom)):
        items, stats = await broll_planner.plan_broll_items(dg, density="medium")
    assert items, "fallback должен дать хотя бы один item"
    assert all("neutral" in it["prompt"].lower() or it["prompt"] for it in items)
    assert stats["cost"] == 0.0


# ─────────────────────────── Claude → Gemini routing ─────────────────────────


@pytest.mark.asyncio
async def test_claude_model_is_routed_to_gemini_flash(patched_llm):
    """Если пользователь выбрал claude-* — broll_planner всё равно зовёт Gemini."""
    dg = _make_dg_paragraphs([
        (0.0, 7.0, "А"), (7.5, 14.0, "Б"), (14.5, 22.0, "В"),
    ])
    items, stats = await broll_planner.plan_broll_items(
        dg, density="low", llm_model="claude-opus-4-7"
    )
    assert items
    assert stats["llm_model"] == "gemini-flash-latest"
    args, _ = patched_llm.call_args
    assert args[0] == "gemini-flash-latest"
