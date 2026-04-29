"""
tree_service.py — Генерация отдельных узлов дерева через SSE-очередь.
Каждая функция кладёт события в queue и сохраняет узел в БД.
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from uuid import uuid4

from app.db.models import ResultNode
from app.db.database import (
    save_tree_node, get_tree_node, update_tree_node_status,
    count_siblings, update_tree_node_stats
)
from app.services.gemini_service import get_model_info
from app.services.llm import get_provider
from app.services.elevenlabs_service import generate_audio as elevenlabs_generate
from app.services.heygen_service import generate_video_from_audio, check_video_status, calculate_heygen_cost
from app.services.deepgram_service import generate_timecodes as deepgram_generate_timecodes
from app.services import submagic_service
from app.services import creatomate_service
from app.services.creatomate_render_builder import build_render_script
from app.services.broll_planner import plan_broll_items, BrollPlannerError

logger = logging.getLogger("tree_service")

HOST_URL = "https://armeykabrain.net"


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────

def _node_to_dict(node: ResultNode) -> dict:
    d = node.model_dump()
    for f in ("params_json", "stats_json", "evaluation_json"):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except Exception:
                pass
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    return d


def _count_nodes_of_type(slug: str, parent_node_id: str, node_type: str) -> int:
    return count_siblings(parent_node_id, node_type)


def _next_title(slug: str, parent_node_id: str, node_type: str) -> str:
    labels = {"script": "Сценарий", "audio": "Аудио", "video": "Видео", "montage": "Монтаж"}
    n = _count_nodes_of_type(slug, parent_node_id, node_type) + 1
    return f"{labels.get(node_type, node_type)} #{n}"


# ──────────────────────────────────────────────────────────────────────────────
# Генерация СЦЕНАРИЯ (Step 3) из узла-статьи
# ──────────────────────────────────────────────────────────────────────────────

async def generate_script_node(queue: asyncio.Queue, slug: str,
                                parent_node_id: str, params: dict):
    """
    Генерирует сценарий для аудио из текста экспертной статьи (Шаг 3).
    params: audio_duration_sec, audio_wpm, style, gemini_model
    """
    parent = get_tree_node(parent_node_id)
    if not parent or not parent.get("content_text"):
        await queue.put({"step": "error", "message": "Родительский узел не найден или пуст"})
        return

    article_text = parent["content_text"]

    # Создаём placeholder-узел в статусе processing
    title = _next_title(slug, parent_node_id, "script")
    node = ResultNode(
        slug=slug,
        node_id=str(uuid4()),
        parent_node_id=parent_node_id,
        node_type="script",
        title=title,
        status="processing",
        position=_count_nodes_of_type(slug, parent_node_id, "script"),
        params_json=json.dumps(params, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    node = save_tree_node(node)
    await queue.put({"step": "node_created", "node": _node_to_dict(node)})

    try:
        duration = params.get("audio_duration_sec", 60)
        wpm = params.get("audio_wpm", 150)
        model = params.get("ai_model") or params.get("gemini_model", "gemini-flash-latest")

        # Резолвим step3-промпт по ключу (если указан)
        prompt_key = params.get("step3_prompt_key", "default")
        prompt_override = None
        if prompt_key and prompt_key != "default":
            from app.core.prompt_manager import PromptManager
            audio_prompts = PromptManager.get_audio_prompts()
            prompt_override = audio_prompts.get(prompt_key)

        llm = get_provider(model)
        await queue.put({"step": 3, "message": f"Генерация аудиосценария через {llm.name.title()} ({model})..."})
        t0 = time.time()
        result = await llm.audio_script(
            article_text, duration=duration, wpm=wpm,
            override=prompt_override, model=model,
        )
        gen_time = round(time.time() - t0, 1)

        if not result or not result.script:
            raise Exception(f"Пустой сценарий от {llm.name.title()}")

        in_cost, out_cost = llm.calculate_cost(result.in_tokens, result.out_tokens, model)
        stats = {
            "model": model,
            "in_tokens": result.in_tokens,
            "out_tokens": result.out_tokens,
            "in_cost": in_cost,
            "out_cost": out_cost,
            "total_cost": in_cost + out_cost,
            "generation_time_sec": gen_time,
        }

        node.status = "completed"
        node.content_text = result.script
        node.stats_json = json.dumps(stats, ensure_ascii=False)
        node = save_tree_node(node)

        await queue.put({"step": "done", "node": _node_to_dict(node)})

    except Exception as e:
        logger.error(f"generate_script_node error: {e}")
        update_tree_node_status(node.node_id, "failed")
        await queue.put({"step": "error", "message": str(e), "node_id": node.node_id})


# ──────────────────────────────────────────────────────────────────────────────
# Генерация АУДИО (Step 4) из узла-сценария
# ──────────────────────────────────────────────────────────────────────────────

async def generate_audio_node(queue: asyncio.Queue, slug: str,
                               parent_node_id: str, params: dict):
    """
    Генерирует аудиофайл через ElevenLabs из текста сценария (Шаг 4).
    params: elevenlabs_model, voice_id, voice_name, audio_wpm,
            stability, similarity_boost, style, use_speaker_boost
    """
    parent = get_tree_node(parent_node_id)
    if not parent or not parent.get("content_text"):
        await queue.put({"step": "error", "message": "Родительский узел сценария не найден"})
        return

    script_text = parent["content_text"]

    title = _next_title(slug, parent_node_id, "audio")
    node = ResultNode(
        slug=slug,
        node_id=str(uuid4()),
        parent_node_id=parent_node_id,
        node_type="audio",
        title=title,
        status="processing",
        position=_count_nodes_of_type(slug, parent_node_id, "audio"),
        params_json=json.dumps(params, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    node = save_tree_node(node)
    await queue.put({"step": "node_created", "node": _node_to_dict(node)})

    try:
        await queue.put({"step": 4, "message": "Генерация аудиофайла через ElevenLabs..."})
        t0 = time.time()

        voice_id = params.get("voice_id", "FGY2WhTYpPnroxEErjIq")
        el_model = params.get("elevenlabs_model", "eleven_v3")
        wpm = params.get("audio_wpm", 150)
        stability = params.get("stability", 0.5)
        similarity_boost = params.get("similarity_boost", 0.75)
        style = params.get("style", 0.25)
        use_speaker_boost = params.get("use_speaker_boost", True)

        # Вычисляем speed для ElevenLabs
        NATIVE_WPM = 150
        speed = round(wpm / NATIVE_WPM, 3)
        speed = max(0.7, min(1.2, speed))

        audio_url_web, audio_url_orig, actual_duration_sec = await elevenlabs_generate(
            text=script_text,
            voice_id=voice_id,
            model_id=el_model,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
            speed=speed,
        )
        gen_time = round(time.time() - t0, 1)

        char_count = len(script_text)
        word_count = len(script_text.split())
        audio_duration = round(word_count / wpm * 60)
        if actual_duration_sec > 0:
            audio_duration = actual_duration_sec
        # Примерная стоимость ElevenLabs (~ $0.0003/символ для Eleven v3)
        cost_per_char = 0.0003 if 'turbo' not in el_model and 'flash' not in el_model else 0.00011
        audio_cost = round(char_count * cost_per_char, 4)

        stats = {
            "elevenlabs_model": el_model,
            "voice_id": voice_id,
            "voice_name": params.get("voice_name", ""),
            "char_count": char_count,
            "wpm": wpm,
            "audio_duration_sec": audio_duration,
            "total_cost": audio_cost,
            "generation_time_sec": gen_time,
        }

        node.status = "completed"
        node.content_url = audio_url_web
        node.content_url_original = audio_url_orig
        node.stats_json = json.dumps(stats, ensure_ascii=False)
        node = save_tree_node(node)

        # Запускаем генерацию таймкодов через Deepgram фоном
        asyncio.create_task(
            _generate_timecodes_background(node.node_id, audio_url_orig)
        )

        await queue.put({"step": "done", "node": _node_to_dict(node)})

    except Exception as e:
        logger.error(f"generate_audio_node error: {e}")
        update_tree_node_status(node.node_id, "failed")
        await queue.put({"step": "error", "message": str(e), "node_id": node.node_id})


async def _generate_timecodes_background(node_id: str, audio_url: str) -> None:
    """Фоновая задача: отправляет аудио в Deepgram и сохраняет таймкоды в stats_json узла."""
    try:
        result = await deepgram_generate_timecodes(audio_url)
        extra_stats = {
            "timecodes_json_url": result["json_url"],
            "timecodes_vtt_url": result["vtt_url"],
            "timecodes_cost": result["cost"],
        }
        update_tree_node_stats(node_id, extra_stats)
        logger.info(f"Timecodes saved for node {node_id}: {result['json_url']}")
    except Exception as e:
        logger.error(f"_generate_timecodes_background error for {node_id}: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Генерация ВИДЕО (Step 5) из узла-аудио
# ──────────────────────────────────────────────────────────────────────────────

async def generate_video_node(queue: asyncio.Queue, slug: str,
                               parent_node_id: str, params: dict):
    """
    Генерирует видео через HeyGen из аудио-узла (Шаг 5).
    params: heygen_engine, avatar_id, avatar_name, video_format, avatar_style
    """
    parent = get_tree_node(parent_node_id)
    if not parent or not parent.get("content_url"):
        await queue.put({"step": "error", "message": "Родительский узел аудио не найден"})
        return

    audio_url = parent["content_url_original"] or parent["content_url"]
    if not audio_url.startswith("http"):
        audio_url = f"{HOST_URL}{audio_url}"

    # Получаем данные из родительского аудио-узла для отображения в заголовке видео
    parent_params = parent.get("params_json") or {}
    if isinstance(parent_params, str):
        try: parent_params = json.loads(parent_params)
        except: parent_params = {}
    parent_stats = parent.get("stats_json") or {}
    if isinstance(parent_stats, str):
        try: parent_stats = json.loads(parent_stats)
        except: parent_stats = {}

    audio_voice_name = (parent_params.get("voice_name") or parent_stats.get("voice_name") or "")
    audio_duration = parent_stats.get("audio_duration_sec") or parent_stats.get("duration_sec", 60)

    # Добавляем голос из аудио в params видео, чтобы фронтенд мог его показать в заголовке
    params_with_voice = {**params, "voice_name": audio_voice_name}

    title = _next_title(slug, parent_node_id, "video")
    node = ResultNode(
        slug=slug,
        node_id=str(uuid4()),
        parent_node_id=parent_node_id,
        node_type="video",
        title=title,
        status="processing",
        position=_count_nodes_of_type(slug, parent_node_id, "video"),
        params_json=json.dumps(params_with_voice, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    node = save_tree_node(node)
    await queue.put({"step": "node_created", "node": _node_to_dict(node)})

    try:
        engine_name = params.get("heygen_engine", "avatar_iv")
        avatar_id = params.get("avatar_id", "")
        video_format = params.get("video_format", "16:9")
        avatar_style = params.get("avatar_style", "auto")

        await queue.put({"step": 5, "message": "Запуск генерации видео в HeyGen (3-15 мин)..."})
        t0 = time.time()

        video_id = await generate_video_from_audio(
            avatar_id=avatar_id,
            audio_url=audio_url,
            title=f"ArmeykaBrain {slug}",
            video_format=video_format,
            heygen_engine=engine_name,
            avatar_style=avatar_style,
        )
        logger.info(f"generate_video_node: HeyGen video_id={video_id}, polling up to 30 min...")

        # Polling статуса (до 30 минут, 180 попыток по 10 сек)
        await queue.put({"step": 5, "message": "Ожидание рендеринга видео HeyGen..."})
        video_url = None
        for attempt in range(180):
            await asyncio.sleep(10)
            status_info = await check_video_status(video_id)
            if status_info["status"] == "completed":
                video_url = status_info["video_url"]
                break
            elif status_info["status"] == "failed":
                heygen_error = status_info.get("error") or "неизвестная ошибка"
                raise Exception(f"HeyGen: ошибка рендеринга — {heygen_error}")
            if attempt % 6 == 5:
                elapsed = round(time.time() - t0)
                logger.info(f"generate_video_node: video_id={video_id}, elapsed={elapsed}s, attempt={attempt+1}/180")

        if not video_url:
            raise Exception(f"HeyGen: превышено время ожидания видео (video_id={video_id})")

        gen_time = round(time.time() - t0)
        cost = calculate_heygen_cost(audio_duration, engine_name)

        stats = {
            "model": "heygen_v2",
            "heygen_engine": engine_name,
            "avatar_id": avatar_id,
            "avatar_name": params.get("avatar_name", ""),
            "video_format": video_format,
            "avatar_style": avatar_style,
            "video_id": video_id,
            "voice_name": audio_voice_name,
            "audio_duration_sec": audio_duration,
            "total_cost": cost,
            "generation_time_sec": gen_time,
            "status": "completed",
        }

        node.status = "completed"
        node.content_url = video_url
        node.stats_json = json.dumps(stats, ensure_ascii=False)
        node = save_tree_node(node)

        await queue.put({"step": "done", "node": _node_to_dict(node)})

    except Exception as e:
        error_msg = str(e)
        logger.error(f"generate_video_node error: {error_msg}")
        error_stats = json.dumps({
            "status": "failed",
            "error_message": error_msg,
            "heygen_engine": params.get("heygen_engine", ""),
            "video_format": params.get("video_format", ""),
        }, ensure_ascii=False)
        update_tree_node_status(node.node_id, "failed", stats_json=error_stats)
        await queue.put({"step": "error", "message": error_msg, "node_id": node.node_id})


# ──────────────────────────────────────────────────────────────────────────────
# Генерация МОНТАЖА (Step 6) из узла-видео через Submagic API
# ──────────────────────────────────────────────────────────────────────────────

async def _ensure_timecodes_for_audio(audio_node: dict, queue: asyncio.Queue) -> dict:
    """Возвращает stats_json аудио, обеспечивая наличие timecodes_json_url.

    Если таймкоды уже сгенерированы — просто возвращает текущие stats. Иначе
    запускает Deepgram, обновляет stats_json узла и возвращает свежие stats.
    """
    stats = audio_node.get("stats_json") or {}
    if isinstance(stats, str):
        try:
            stats = json.loads(stats)
        except Exception:
            stats = {}

    if stats.get("timecodes_json_url"):
        return stats

    audio_url = audio_node.get("content_url_original") or audio_node.get("content_url")
    if not audio_url:
        raise Exception("У родительского аудио-узла нет ссылки на файл")

    await queue.put({"step": 6, "message": "Генерация таймкодов через Deepgram (~30-60с)..."})
    result = await deepgram_generate_timecodes(audio_url)
    extra = {
        "timecodes_json_url": result["json_url"],
        "timecodes_vtt_url": result["vtt_url"],
        "timecodes_cost": result["cost"],
    }
    update_tree_node_stats(audio_node["node_id"], extra)
    stats.update(extra)
    return stats


def _find_parent_audio(video_node: dict) -> dict | None:
    """video → script-родитель не нужен; video.parent_node_id → audio-узел."""
    parent_id = video_node.get("parent_node_id")
    if not parent_id:
        return None
    audio_node = get_tree_node(parent_id)
    if audio_node and audio_node.get("node_type") == "audio":
        return audio_node
    return None


def _load_deepgram_json(timecodes_url: str) -> dict:
    """Читает локальный tc_<uid>.json. URL формата /static/audio/tc_xxx.json."""
    local_path = (timecodes_url or "").lstrip("/")
    if not local_path:
        raise Exception("timecodes_json_url пуст")
    with open(local_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def generate_montage_node(queue: asyncio.Queue, slug: str,
                                 parent_node_id: str, params: dict):
    """
    Создаёт видео-монтаж через Submagic API из video-узла.

    Режимы (params["mode"]):
      - "auto"  (по умолчанию): чистый Submagic с magicBrolls/magicZooms.
      - "smart": перед запуском Submagic берём Deepgram-таймкоды родительского
        аудио, отбираем сегменты, генерируем через LLM B-roll-промпты с фильтром
        иностранной символики и передаём как items[] в Submagic.

    params: mode, template_name, magic_zooms, magic_brolls, magic_brolls_pct,
            remove_silence_pace, remove_bad_takes, clean_audio,
            (smart-only:) density, topic_hint, layout, russia_only, extra_prompt, llm_model
    """
    parent = get_tree_node(parent_node_id)
    if not parent or not parent.get("content_url"):
        await queue.put({"step": "error", "message": "Родительский узел видео не найден"})
        return

    video_url = parent["content_url"]
    if not video_url.startswith("http"):
        video_url = f"{HOST_URL}{video_url}"

    parent_stats = parent.get("stats_json") or {}
    if isinstance(parent_stats, str):
        try:
            parent_stats = json.loads(parent_stats)
        except Exception:
            parent_stats = {}

    title = _next_title(slug, parent_node_id, "montage")
    node = ResultNode(
        slug=slug,
        node_id=str(uuid4()),
        parent_node_id=parent_node_id,
        node_type="montage",
        title=title,
        status="processing",
        position=_count_nodes_of_type(slug, parent_node_id, "montage"),
        params_json=json.dumps(params, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    node = save_tree_node(node)
    await queue.put({"step": "node_created", "node": _node_to_dict(node)})

    service = (params.get("service") or "submagic").lower()
    if service not in {"submagic", "creatomate"}:
        service = "submagic"

    try:
        if service == "creatomate":
            stats, download_url = await _run_creatomate_montage(
                queue=queue, slug=slug, title=title,
                video_url=video_url, parent=parent,
                parent_stats=parent_stats, params=params,
            )
        else:
            stats, download_url = await _run_submagic_montage(
                queue=queue, slug=slug, title=title,
                video_url=video_url, parent=parent,
                parent_stats=parent_stats, params=params,
            )

        node.status = "completed"
        node.content_url = download_url
        node.stats_json = json.dumps(stats, ensure_ascii=False)
        node = save_tree_node(node)

        await queue.put({"step": "done", "node": _node_to_dict(node)})

    except Exception as e:
        error_msg = str(e)
        logger.error(f"generate_montage_node error ({service}): {error_msg}")
        error_stats = json.dumps({
            "service": service,
            "status": "failed",
            "error_message": error_msg,
        }, ensure_ascii=False)
        update_tree_node_status(node.node_id, "failed", stats_json=error_stats)
        await queue.put({"step": "error", "message": error_msg, "node_id": node.node_id})


# ──────────────────────────────────────────────────────────────────────────────
# Submagic montage runner
# ──────────────────────────────────────────────────────────────────────────────

async def _run_submagic_montage(*, queue, slug, title, video_url, parent, parent_stats, params) -> tuple[dict, str]:
    mode = (params.get("mode") or "auto").lower()
    if mode not in {"auto", "smart"}:
        mode = "auto"

    smart_items: list[dict] | None = None
    smart_stats: dict = {}

    if mode == "smart":
        audio_node = _find_parent_audio(parent)
        if not audio_node:
            raise Exception("Не найден родительский аудио-узел для Smart-режима")

        audio_stats = await _ensure_timecodes_for_audio(audio_node, queue)
        tc_url = audio_stats.get("timecodes_json_url")
        if not tc_url:
            raise Exception("Не удалось получить таймкоды для Smart-режима")

        await queue.put({"step": 6, "message": "Анализ таймкодов и генерация B-roll-промптов..."})
        try:
            deepgram_json = _load_deepgram_json(tc_url)
        except FileNotFoundError:
            raise Exception(f"Файл таймкодов не найден: {tc_url}")

        broll_source = (params.get("broll_source") or "ai").lower()
        _EXTERNAL_PROVIDERS = {"pexels", "pixabay", "pexels_pixabay", "veo", "runway"}

        if broll_source in _EXTERNAL_PROVIDERS:
            # ── Внешний B-roll: Pexels / Pixabay / Veo / Runway ──────────────
            # Шаг 1: планировщик генерирует временны́е слоты + запросы/промпты
            from app.services.broll_planner import plan_broll_for_creatomate
            from app.services.broll_providers import get_provider
            from app.services.broll_providers.base import ProviderError

            try:
                broll_plan, planner_stats = await plan_broll_for_creatomate(
                    deepgram_json,
                    density=params.get("density", "medium"),
                    clip_duration=int(params.get("clip_duration", 5)),
                    topic_hint=params.get("topic_hint", "auto"),
                    extra_prompt=params.get("extra_prompt", ""),
                    llm_model=params.get("llm_model", "gemini-flash-latest"),
                    russia_only=bool(params.get("russia_only", True)),
                    provider_kind=("ai" if broll_source in {"veo", "runway"} else "stock"),
                )
            except Exception as bpe:
                raise Exception(f"Smart-планировщик (ext): {bpe}")

            await queue.put({
                "step": 6,
                "message": f"Поиск/генерация {len(broll_plan)} B-roll клипов через {broll_source}..."
            })

            provider = get_provider(broll_source)
            parent_video_format = parent_stats.get("video_format", "9:16")
            orientation = (
                "portrait" if parent_video_format in ("9:16", "4:5")
                else ("square" if parent_video_format == "1:1" else "landscape")
            )
            concurrency = 1 if provider.kind == "ai" else 3
            sem = asyncio.Semaphore(concurrency)
            fetch_errors: list[str] = []

            async def _fetch_ext(item: dict) -> dict | None:
                async with sem:
                    query = item.get("query_en") if provider.kind == "stock" else item.get("prompt")
                    if not query:
                        return None
                    try:
                        clip = await provider.search(query, duration_sec=item["duration"], orientation=orientation)
                    except ProviderError as pe:
                        fetch_errors.append(str(pe)[:120])
                        logger.warning(f"Provider {provider.name} failed: {pe}")
                        return None
                    if not clip:
                        return None
                    return {"url": clip["url"], "start": item["start"], "duration": item["duration"]}

            raw_clips = await asyncio.gather(*(_fetch_ext(it) for it in broll_plan))
            ext_clips = [c for c in raw_clips if c]

            if not ext_clips:
                first_err = fetch_errors[0] if fetch_errors else "провайдер не вернул результатов"
                await queue.put({"step": 6, "warning": (
                    f"⚠️ B-roll от {broll_source} не получен: {first_err}. "
                    "Монтаж будет создан без B-roll вставок."
                )})
            else:
                # Шаг 2: загружаем каждый клип в Submagic User Media Library
                await queue.put({
                    "step": 6,
                    "message": f"Загрузка {len(ext_clips)} клипов в Submagic Media Library..."
                })
                layout_raw = params.get("layout", "cover")
                # Submagic pip-значение: "pip" → "pip-bottom-right"
                layout_sm = (
                    "pip-bottom-right" if layout_raw == "pip"
                    else layout_raw
                )

                upload_tasks = [submagic_service.upload_user_media(c["url"]) for c in ext_clips]
                media_ids = await asyncio.gather(*upload_tasks, return_exceptions=True)

                # Шаг 3: ждём пока медиа будут готовы (Submagic загружает их асинхронно)
                await queue.put({"step": 6, "message": "Ожидание обработки медиа в Submagic..."})
                valid_ids = []
                for mid in media_ids:
                    if isinstance(mid, Exception):
                        logger.warning(f"upload_user_media error: {mid}")
                        fetch_errors.append(str(mid)[:80])
                        continue
                    valid_ids.append(mid)

                ready_ids = []
                for mid in valid_ids:
                    ok = await submagic_service.wait_for_user_media(mid, max_wait_sec=90)
                    if ok:
                        ready_ids.append(mid)
                    else:
                        logger.warning(f"Submagic: media {mid} не готово за 90 с, пропускаем")

                # Шаг 4: строим items[] для Submagic в формате user-media
                if ready_ids:
                    smart_items = []
                    id_iter = iter(ready_ids)
                    for clip in ext_clips:
                        try:
                            mid = next(id_iter)
                        except StopIteration:
                            break
                        smart_items.append({
                            "type": "user-media",
                            "startTime": round(clip["start"], 2),
                            "endTime":   round(clip["start"] + clip["duration"], 2),
                            "userMediaId": mid,
                            "layout": layout_sm,
                        })
                    logger.info(f"Submagic ext B-roll: {len(smart_items)} user-media items готово")
                    smart_stats = {
                        "broll_source": broll_source,
                        "planned": len(broll_plan),
                        "fetched": len(ext_clips),
                        "uploaded": len(ready_ids),
                        "items": len(smart_items),
                        "planner_cost_usd": planner_stats.get("cost", 0.0),
                    }
                else:
                    await queue.put({"step": 6, "warning": (
                        "⚠️ Все B-roll клипы не прошли обработку в Submagic. "
                        "Монтаж будет создан без B-roll вставок."
                    )})

        else:
            # ── Встроенный AI B-roll Submagic (тип: ai-broll) ────────────────
            try:
                smart_items, smart_stats = await plan_broll_items(
                    deepgram_json,
                    density=params.get("density", "medium"),
                    clip_duration=int(params.get("clip_duration", 5)),
                    topic_hint=params.get("topic_hint", "auto"),
                    layout=params.get("layout", "cover"),
                    extra_prompt=params.get("extra_prompt", ""),
                    llm_model=params.get("llm_model", "gemini-flash-latest"),
                    russia_only=bool(params.get("russia_only", True)),
                )
            except BrollPlannerError as bpe:
                raise Exception(f"Smart-планировщик: {bpe}")

        logger.info(
            f"Smart broll ({broll_source}): {len(smart_items or [])} items, "
            f"video={smart_stats.get('video_duration_sec')}s, "
            f"llm_cost=${smart_stats.get('cost', smart_stats.get('planner_cost_usd', 0)):.5f}"
        )

    dictionary = params.get("dictionary") or ["Армейка Нэт", "ArmeykaBrain", "Armeykanet"]

    await queue.put({"step": 6, "message": "Создание проекта в Submagic..."})
    t0 = time.time()

    project = await submagic_service.create_project(
        video_url=video_url,
        title=f"ArmeykaBrain {slug} — {title}",
        language=params.get("language", "ru"),
        template_name=params.get("template_name", "Hormozi 2"),
        magic_zooms=params.get("magic_zooms", True),
        magic_brolls=params.get("magic_brolls", False) if mode == "auto" else False,
        magic_brolls_pct=params.get("magic_brolls_pct", 50),
        remove_silence_pace=params.get("remove_silence_pace"),
        remove_bad_takes=params.get("remove_bad_takes", False),
        clean_audio=params.get("clean_audio", False),
        dictionary=dictionary,
        items=smart_items,
    )
    project_id = project["id"]
    logger.info(f"Submagic project created: id={project_id} for slug={slug}")

    await queue.put({"step": 6, "message": "Submagic: обработка и транскрипция видео..."})
    status = {}
    for attempt in range(180):
        await asyncio.sleep(10)
        status = await submagic_service.get_project(project_id)
        current_status = status.get("status", "")

        if current_status == "completed":
            break
        elif current_status == "failed":
            reason = status.get("failureReason") or "неизвестная ошибка"
            raise Exception(f"Submagic: ошибка обработки — {reason}")

        if attempt % 6 == 5:
            elapsed = round(time.time() - t0)
            logger.info(f"Submagic project {project_id}: status={current_status}, elapsed={elapsed}s")

    if not status.get("downloadUrl") and not status.get("directUrl"):
        await queue.put({"step": 6, "message": "Submagic: рендеринг смонтированного видео..."})
        video_meta = status.get("videoMetaData") or {}
        await submagic_service.export_project(
            project_id,
            fps=video_meta.get("fps"),
            width=video_meta.get("width"),
            height=video_meta.get("height"),
        )

        for attempt in range(120):
            await asyncio.sleep(10)
            status = await submagic_service.get_project(project_id)
            if status.get("status") == "completed" and (status.get("downloadUrl") or status.get("directUrl")):
                break
            elif status.get("status") == "failed":
                raise Exception("Submagic: ошибка экспорта")
            if attempt % 6 == 5:
                elapsed = round(time.time() - t0)
                logger.info(f"Submagic export {project_id}: status={status.get('status')}, elapsed={elapsed}s")

    download_url = status.get("directUrl") or status.get("downloadUrl") or ""
    preview_url = status.get("previewUrl") or ""

    if not download_url:
        raise Exception("Submagic: видео не содержит ссылки на скачивание")

    gen_time = round(time.time() - t0)

    video_meta = status.get("videoMetaData") or {}
    video_duration = video_meta.get("duration", 0)

    submagic_cost = float(parent_stats.get("total_cost") or 0) * 0  # Submagic не возвращает цену

    stats = {
        "service": "submagic",
        "submagic_project_id": project_id,
        "mode": mode,
        "template_name": params.get("template_name", "Hormozi 2"),
        "magic_zooms": params.get("magic_zooms", True),
        "magic_brolls": params.get("magic_brolls", False) if mode == "auto" else False,
        "magic_brolls_pct": params.get("magic_brolls_pct", 50),
        "remove_silence_pace": params.get("remove_silence_pace"),
        "remove_bad_takes": params.get("remove_bad_takes", False),
        "clean_audio": params.get("clean_audio", False),
        "hide_captions": params.get("hide_captions", False),
        "video_duration_sec": video_duration,
        "video_width": video_meta.get("width"),
        "video_height": video_meta.get("height"),
        "preview_url": preview_url,
        "generation_time_sec": gen_time,
        "status": "completed",
    }
    if mode == "smart":
        broll_source_val = params.get("broll_source", "ai")
        stats.update({
            "broll_source": broll_source_val,
            "density": params.get("density", "medium"),
            "clip_duration": int(params.get("clip_duration", 5)),
            "topic_hint": params.get("topic_hint", "auto"),
            "layout": params.get("layout", "cover"),
            "russia_only": bool(params.get("russia_only", True)),
            "extra_prompt": (params.get("extra_prompt") or "")[:300],
            "broll_items_count": smart_stats.get("items", smart_stats.get("broll_items_count", len(smart_items or []))),
            "broll_llm_model": smart_stats.get("llm_model"),
            "broll_llm_in_tokens": smart_stats.get("in_tokens", 0),
            "broll_llm_out_tokens": smart_stats.get("out_tokens", 0),
            "broll_llm_cost": smart_stats.get("cost", smart_stats.get("planner_cost_usd", 0.0)),
            "total_cost": round(
                submagic_cost + float(smart_stats.get("cost", smart_stats.get("planner_cost_usd", 0.0))),
                6,
            ),
        })

    return stats, download_url


# ──────────────────────────────────────────────────────────────────────────────
# Creatomate montage runner
# ──────────────────────────────────────────────────────────────────────────────

async def _run_creatomate_montage(*, queue, slug, title, video_url, parent, parent_stats, params) -> tuple[dict, str]:
    """
    Запускает Creatomate-рендер. Параметры из params:
      video_format ('9:16'/'16:9'/'1:1'/'4:5'), fps, subtitle_preset,
      transcript_effect, transcript_split, subtitle_y, max_chars_per_line,
      music_url, music_volume_pct,
      broll_provider ('off'/'pexels'/...), broll_density, broll_clip_duration,
      intro_image, intro_text, intro_duration,
      outro_image, outro_text, outro_duration,
      watermark_url, watermark_position,
      color_filter, color_filter_value
    """
    from app.services.creatomate_render_builder import build_render_script

    t0 = time.time()

    # Длительность исходного видео — используем родительские данные если есть
    duration_sec = (
        params.get("duration_sec")
        or parent_stats.get("video_duration_sec")
        or parent_stats.get("audio_duration")
        or None
    )
    if duration_sec:
        try:
            duration_sec = float(duration_sec)
        except (TypeError, ValueError):
            duration_sec = None

    video_format = params.get("video_format") or "9:16"
    fps = int(params.get("fps") or 30)

    # B-roll — этап 2/3 (заглушка для MVP)
    broll_clips: list[dict] = []
    broll_stats: dict = {}
    broll_provider_key = (params.get("broll_provider") or "off").lower()

    if broll_provider_key not in ("off", "", None):
        # Этап 2: интеграция стоковых/AI провайдеров
        try:
            from app.services.broll_planner import plan_broll_for_creatomate
            from app.services.broll_providers import get_provider, ProviderError

            audio_node = _find_parent_audio(parent)
            if not audio_node:
                raise Exception("Не найден родительский аудио-узел для B-roll")
            audio_stats = await _ensure_timecodes_for_audio(audio_node, queue)
            tc_url = audio_stats.get("timecodes_json_url")
            if not tc_url:
                raise Exception("Не удалось получить таймкоды для B-roll")

            await queue.put({"step": 6, "message": "Анализ таймкодов для B-roll..."})
            deepgram_json = _load_deepgram_json(tc_url)

            broll_plan, planner_stats = await plan_broll_for_creatomate(
                deepgram_json,
                density=params.get("broll_density", "medium"),
                clip_duration=int(params.get("broll_clip_duration", 5)),
                topic_hint=params.get("broll_topic", "auto"),
                extra_prompt=params.get("broll_extra_prompt", ""),
                llm_model=params.get("broll_llm_model", "gemini-flash-latest"),
                russia_only=bool(params.get("broll_russia_only", True)),
                provider_kind=("ai" if broll_provider_key in {"veo", "runway", "luma"} else "stock"),
            )

            await queue.put({"step": 6, "message": f"Поиск/генерация {len(broll_plan)} B-roll клипов через {broll_provider_key}..."})
            provider = get_provider(broll_provider_key)
            orientation = "portrait" if video_format in ("9:16", "4:5") else ("square" if video_format == "1:1" else "landscape")

            # Параллельный поиск с лимитом (AI-провайдеры — последовательно,
            # т.к. генерация Veo занимает 1-4 минуты и расходует кредиты)
            concurrency = 1 if provider.kind == "ai" else 3
            sem = asyncio.Semaphore(concurrency)
            fetch_errors: list[str] = []

            async def _fetch_one(item: dict) -> dict | None:
                async with sem:
                    query = item.get("query_en") if provider.kind == "stock" else item.get("prompt")
                    if not query:
                        return None
                    try:
                        clip = await provider.search(query, duration_sec=item["duration"], orientation=orientation)
                    except ProviderError as pe:
                        short = str(pe)[:120]
                        logger.warning(f"Provider {provider.name} failed for '{query[:40]}': {pe}")
                        fetch_errors.append(short)
                        return None
                    if not clip:
                        return None
                    return {
                        "source": clip["url"],
                        "time": item["start"],
                        "duration": item["duration"],
                        "_cost_usd": clip.get("cost_usd", 0.0),
                        "_query": query,
                    }

            results = await asyncio.gather(*(_fetch_one(it) for it in broll_plan))
            broll_clips = [r for r in results if r]
            for idx, bc in enumerate(broll_clips, 1):
                logger.info(
                    f"B-roll clip {idx}: time={bc.get('time')}s "
                    f"dur={bc.get('duration')}s url={str(bc.get('source',''))[:80]}"
                )

            # Предупреждаем пользователя если часть или все клипы не получены
            if fetch_errors and not broll_clips:
                first_err = fetch_errors[0]
                await queue.put({"step": 6, "warning": (
                    f"⚠️ B-roll от {broll_provider_key} не получен: {first_err}. "
                    "Монтаж будет создан без B-roll вставок."
                )})
            elif fetch_errors:
                await queue.put({"step": 6, "warning": (
                    f"⚠️ {len(fetch_errors)} из {len(broll_plan)} B-roll клипов не получены "
                    f"({broll_provider_key}): {fetch_errors[0]}"
                )})

            broll_stats = {
                "provider": provider.name,
                "kind": provider.kind,
                "planned_count": len(broll_plan),
                "fetched_count": len(broll_clips),
                "failed_count": len(fetch_errors),
                "first_error": fetch_errors[0] if fetch_errors else None,
                "planner_cost_usd": planner_stats.get("cost", 0.0),
                "broll_cost_usd": round(sum(r.get("_cost_usd", 0.0) for r in broll_clips), 4),
                "llm_model": planner_stats.get("llm_model"),
                "in_tokens": planner_stats.get("in_tokens", 0),
                "out_tokens": planner_stats.get("out_tokens", 0),
            }
        except Exception as bex:
            err_msg = str(bex)
            logger.warning(f"B-roll generation failed, продолжаем без B-roll: {err_msg}")
            await queue.put({"step": 6, "warning": (
                f"⚠️ B-roll не получен ({broll_provider_key}): {err_msg[:150]}. "
                "Монтаж будет создан без B-roll вставок."
            )})
            broll_stats = {"error": err_msg, "fetched_count": 0}
            broll_clips = []

    await queue.put({"step": 6, "message": "Сборка RenderScript для Creatomate..."})
    render_script = build_render_script(
        video_url=video_url,
        duration_sec=duration_sec,
        video_format=video_format,
        fps=fps,
        subtitle_preset=params.get("subtitle_preset", "hormozi_white"),
        transcript_effect=params.get("transcript_effect", "karaoke"),
        transcript_split=params.get("transcript_split", "word"),
        subtitle_y=params.get("subtitle_y", "82%"),
        max_chars_per_line=params.get("max_chars_per_line", 32),
        music_url=params.get("music_url") or None,
        music_volume_pct=int(params.get("music_volume_pct", 25)),
        broll_clips=broll_clips or None,
        broll_layout=params.get("broll_layout", "overlay"),
        intro_image=params.get("intro_image") or None,
        intro_text=params.get("intro_text") or None,
        intro_duration=float(params.get("intro_duration", 2.0)),
        outro_image=params.get("outro_image") or None,
        outro_text=params.get("outro_text") or None,
        outro_duration=float(params.get("outro_duration", 2.5)),
        watermark_url=params.get("watermark_url") or None,
        watermark_position=params.get("watermark_position", "top-right"),
        color_filter=params.get("color_filter") or None,
        color_filter_value=params.get("color_filter_value") or None,
    )

    await queue.put({"step": 6, "message": "Creatomate: запуск рендера..."})
    render_obj = await creatomate_service.create_render(render_script)
    render_id = render_obj["id"]
    logger.info(f"Creatomate render created: id={render_id} for slug={slug}")

    await queue.put({"step": 6, "message": "Creatomate: рендеринг видео..."})
    final = await creatomate_service.wait_for_render(render_id, interval_sec=5, max_attempts=360)

    download_url = final.get("url") or final.get("snapshot_url") or ""
    if not download_url:
        raise Exception("Creatomate: финальный объект не содержит URL")

    gen_time = round(time.time() - t0)
    width = render_script.get("width")
    height = render_script.get("height")
    actual_duration = final.get("duration") or duration_sec or 0

    credits = creatomate_service.calculate_credits(
        width=width, height=height, fps=fps, duration_sec=actual_duration or 0,
    )
    render_cost_usd = creatomate_service.calculate_cost_usd(credits)

    total_cost = round(
        render_cost_usd
        + float(broll_stats.get("planner_cost_usd", 0.0))
        + float(broll_stats.get("broll_cost_usd", 0.0)),
        4,
    )

    stats = {
        "service": "creatomate",
        "creatomate_render_id": render_id,
        "video_format": video_format,
        "fps": fps,
        "video_width": width,
        "video_height": height,
        "video_duration_sec": actual_duration,
        "subtitle_preset": params.get("subtitle_preset", "hormozi_white"),
        "transcript_effect": params.get("transcript_effect", "karaoke"),
        "transcript_split": params.get("transcript_split", "word"),
        "music_url": params.get("music_url") or None,
        "music_volume_pct": int(params.get("music_volume_pct", 25)),
        "watermark_url": params.get("watermark_url") or None,
        "color_filter": params.get("color_filter") or None,
        "intro_text": params.get("intro_text") or None,
        "outro_text": params.get("outro_text") or None,
        "broll_layout": params.get("broll_layout", "overlay") if broll_stats else None,
        "credits": credits,
        "render_cost_usd": render_cost_usd,
        "total_cost": total_cost,
        "generation_time_sec": gen_time,
        "status": "completed",
    }
    if broll_stats:
        stats["broll"] = broll_stats

    return stats, download_url


# ──────────────────────────────────────────────────────────────────────────────
# Диспетчер: определяет какую функцию вызвать
# ──────────────────────────────────────────────────────────────────────────────

async def dispatch_generate(queue: asyncio.Queue, slug: str,
                             parent_node_id: str, target_type: str, params: dict):
    if target_type == "script":
        await generate_script_node(queue, slug, parent_node_id, params)
    elif target_type == "audio":
        await generate_audio_node(queue, slug, parent_node_id, params)
    elif target_type == "video":
        await generate_video_node(queue, slug, parent_node_id, params)
    elif target_type == "montage":
        await generate_montage_node(queue, slug, parent_node_id, params)
    else:
        await queue.put({"step": "error", "message": f"Неизвестный тип узла: {target_type}"})
