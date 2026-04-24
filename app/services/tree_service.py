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
    labels = {"script": "Сценарий", "audio": "Аудио", "video": "Видео"}
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
    else:
        await queue.put({"step": "error", "message": f"Неизвестный тип узла: {target_type}"})
