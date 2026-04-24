"""Эндпоинты основного pipeline: /api/query, /api/stream_query, /api/upgrade_to_audio,
/api/generate_audio_only, /api/generate_video_only, /api/evaluate_audio."""

from __future__ import annotations

import os
import json
import time
import asyncio
import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.core.exceptions import APIError, NotFoundError, ExternalAPIError
from app.core.state import background_tasks, active_streams
from app.db.database import (
    log_message,
    get_result_by_slug,
    add_additional_audio,
    save_main_evaluation,
    save_additional_evaluation,
)
from app.models.requests import (
    QueryRequest, AudioRequest, UpgradeAudioRequest,
    GenerateVideoRequest, EvaluateRequest,
)
from app.services.core import process_query_logic, process_upgrade_to_audio_logic
from app.services.elevenlabs_service import generate_audio
from app.services.gemini_service import evaluate_audio_quality

logger = logging.getLogger("api")
router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query")
async def process_user_query(req: QueryRequest):
    """Основной эндпоинт обработки вопроса (фоновая потоковая генерация)."""
    logger.info(f"Получен запрос: модель={req.model}, стиль={req.style}, текст='{req.question[:50]}...'")
    log_message("web_user", "web_interface", "in", req.question)

    from app.db.database import reserve_slug
    slug = reserve_slug(req.question, req.tab_type)

    queue = asyncio.Queue()
    active_streams[slug] = queue

    task = asyncio.create_task(
        process_query_logic(
            queue=queue,
            slug=slug,
            question=req.question,
            model=req.model,
            model1=req.model1 or req.model,
            model2=req.model2 or req.model,
            model3=req.model3 or req.model,
            style=req.style,
            context_threshold=req.context_threshold,
            send_prompts=req.send_prompts,
            max_length=req.max_length,
            tab_type=req.tab_type,
            audio_duration=req.audio_duration,
            elevenlabs_model=req.elevenlabs_model,
            audio_wpm=req.audio_wpm,
            elevenlabs_voice=req.elevenlabs_voice,
            audio_style=req.audio_style,
            use_speaker_boost=req.use_speaker_boost,
            audio_stability=req.audio_stability,
            audio_similarity_boost=req.audio_similarity_boost,
            heygen_avatar_id=req.heygen_avatar_id,
            video_format=req.video_format,
            heygen_engine=req.heygen_engine,
            avatar_style=req.avatar_style if hasattr(req, 'avatar_style') else "auto",
            custom_prompts=req.custom_prompts or {},
            audio_prompt_name=req.audio_prompt_name,
        )
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    return {"success": True, "slug": slug, "url": f"/text/{slug}"}


@router.get("/stream_query")
async def stream_query(slug: str):
    """SSE-поток для начатого ранее запроса."""
    queue = active_streams.get(slug)
    if not queue:
        return EventSourceResponse(iter([]))

    async def generator():
        try:
            while True:
                chunk = await queue.get()

                if chunk.get("step") == "done":
                    log_message("web_user", "web_interface", "out", chunk["result"]["answer"])
                    logger.info("Запрос успешно обработан")
                    yield {"data": json.dumps(chunk, ensure_ascii=False)}
                    break
                elif chunk.get("step") == "error":
                    log_message("web_user", "web_interface", "out", chunk["message"])
                    logger.error(f"Ошибка при обработке: {chunk['message']}")
                    yield {"data": json.dumps(chunk, ensure_ascii=False)}
                    break

                yield {"data": json.dumps(chunk, ensure_ascii=False)}
        except asyncio.CancelledError:
            logger.info("Клиент отключился, но фоновая генерация продолжается.")
        except Exception as e:
            logger.exception("Непредвиденная ошибка генератора")
            yield {"data": json.dumps({"step": "error", "message": f"Внутренняя ошибка: {str(e)}"}, ensure_ascii=False)}
        finally:
            active_streams.pop(slug, None)

    return EventSourceResponse(generator())


@router.post("/upgrade_to_audio")
async def upgrade_to_audio(req: UpgradeAudioRequest):
    """Апгрейд текстового результата до аудио-сценария и озвучки."""
    result_data = get_result_by_slug(req.slug)
    if not result_data:
        raise NotFoundError("Результат не найден")

    queue = asyncio.Queue()

    task = asyncio.create_task(
        process_upgrade_to_audio_logic(
            queue=queue,
            slug=req.slug,
            raw_answer=result_data["answer"],
            audio_duration=req.audio_duration,
            elevenlabs_model=req.elevenlabs_model,
            audio_wpm=req.audio_wpm,
            elevenlabs_voice=req.elevenlabs_voice,
            audio_style=req.audio_style,
            use_speaker_boost=req.use_speaker_boost,
            audio_stability=req.audio_stability,
            audio_similarity_boost=req.audio_similarity_boost,
            previous_total_cost=result_data.get("total_stats", {}).get("total_cost", 0.0)
                if isinstance(result_data.get("total_stats"), dict) else 0.0,
            generate_video=req.generate_video,
            heygen_avatar_id=req.heygen_avatar_id,
            video_format=req.video_format,
            heygen_engine=req.heygen_engine,
            avatar_style=req.avatar_style if hasattr(req, 'avatar_style') else "auto",
        )
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    async def generator():
        try:
            while True:
                chunk = await queue.get()
                if chunk.get("step") in ("done", "error"):
                    yield {"data": json.dumps(chunk, ensure_ascii=False)}
                    break
                yield {"data": json.dumps(chunk, ensure_ascii=False)}
        except asyncio.CancelledError:
            logger.info("Клиент отключился, но апгрейд аудио продолжается.")
        except Exception as e:
            logger.exception("Непредвиденная ошибка генератора апгрейда")
            yield {"data": json.dumps({"step": "error", "message": f"Внутренняя ошибка: {str(e)}"}, ensure_ascii=False)}

    return EventSourceResponse(generator())


@router.post("/generate_audio_only")
async def process_generate_audio_only(req: AudioRequest):
    """Дополнительная озвучка из готового текста."""
    try:
        speed = max(0.7, min(req.audio_wpm / 150.0, 1.2))
        audio_url_web, audio_url_orig = await generate_audio(
            text=req.text,
            model_id=req.elevenlabs_model,
            voice_id=req.elevenlabs_voice,
            speed=speed,
            stability=req.stability,
            similarity_boost=req.similarity_boost,
            style=req.style,
            use_speaker_boost=req.use_speaker_boost,
        )

        char_count = len(req.text)
        if "turbo" in req.elevenlabs_model or "flash" in req.elevenlabs_model:
            eleven_cost = (char_count / 1000) * 0.15
        else:
            eleven_cost = (char_count / 1000) * 0.30

        audio_data = {
            "audio_url": audio_url_web,
            "audio_url_original": audio_url_orig,
            "speed": speed,
            "wpm": req.audio_wpm,
            "model": req.elevenlabs_model,
            "voice": req.elevenlabs_voice,
            "stability": req.stability,
            "similarity_boost": req.similarity_boost,
            "style": req.style,
            "use_speaker_boost": req.use_speaker_boost,
            "cost": eleven_cost,
        }

        if req.slug:
            add_additional_audio(req.slug, audio_data)

        return {
            "success": True,
            "audio_url": audio_url_web,
            "audio_url_original": audio_url_orig,
            "speed": speed,
            "wpm": req.audio_wpm,
            "model": req.elevenlabs_model,
            "voice": req.elevenlabs_voice,
            "stability": req.stability,
            "similarity_boost": req.similarity_boost,
            "style": req.style,
            "use_speaker_boost": req.use_speaker_boost,
            "cost": eleven_cost,
        }
    except APIError:
        raise
    except Exception as e:
        logger.exception("Ошибка при генерации дополнительного аудио")
        raise ExternalAPIError(message=f"Ошибка генерации аудио: {str(e)}", service_name="ElevenLabs")


@router.post("/generate_video_only")
async def process_generate_video_only(req: GenerateVideoRequest):
    """Генерация дополнительного/основного видео из аудио."""
    from app.services.heygen_service import generate_video_from_audio, calculate_heygen_cost
    from app.db.database import update_result_with_video
    try:
        host_url = "https://armeykabrain.net"
        public_audio_url = req.audio_url if req.audio_url.startswith("http") else f"{host_url}{req.audio_url}"

        step5_video_id = await generate_video_from_audio(
            avatar_id=req.heygen_avatar_id,
            audio_url=public_audio_url,
            title="ArmeykaBrain Video",
            video_format=req.video_format,
            heygen_engine=req.heygen_engine,
            avatar_style=req.avatar_style,
        )

        duration_sec = 60
        result_data = get_result_by_slug(req.slug)
        if result_data:
            if req.is_main:
                stats = result_data.get("step4_stats", {})
                if stats and isinstance(stats, dict):
                    duration_sec = stats.get("duration_sec", 60)
            else:
                additional_audios = result_data.get("additional_audios_list", [])
                for aud in additional_audios:
                    if aud.get("audio_url") == req.audio_url or aud.get("audio_url_original") == req.audio_url:
                        if "char_count" in aud and "wpm" in aud:
                            duration_sec = int((aud["char_count"] / 5) / aud["wpm"] * 60)
                        break

        step5_cost = calculate_heygen_cost(duration_sec, req.heygen_engine)

        step5_stats = {
            "model": "heygen_v2",
            "avatar_id": req.heygen_avatar_id,
            "video_id": step5_video_id,
            "total_cost": step5_cost,
            "status": "pending",
            "started_at": int(time.time()),
        }

        if req.is_main:
            update_result_with_video(req.slug, step5_video_id, json.dumps(step5_stats, ensure_ascii=False))
        else:
            from app.db.database import save_additional_video_stats
            save_additional_video_stats(req.slug, req.audio_url, step5_video_id, step5_stats)

        return {"success": True, "video_id": step5_video_id, "stats": step5_stats}
    except Exception as e:
        logger.exception("Ошибка при генерации видео")
        raise ExternalAPIError(message=f"Ошибка генерации видео: {str(e)}", service_name="HeyGen")


@router.post("/evaluate_audio")
async def evaluate_audio(req: EvaluateRequest):
    """Оценивает качество сгенерированного аудио через Gemini."""
    try:
        audio_path = req.audio_url.lstrip("/")
        if not os.path.exists(audio_path):
            raise NotFoundError("Файл аудио не найден на сервере")

        params = {
            "model": req.elevenlabs_model,
            "voice": req.elevenlabs_voice,
            "stability": req.stability,
            "similarity": req.similarity_boost,
            "style": req.style,
            "use_speaker_boost": req.use_speaker_boost,
        }

        result = await evaluate_audio_quality(audio_path, req.text, params)
        if "error" in result:
            raise ExternalAPIError(message=result["error"], service_name="Gemini")

        if req.slug:
            if req.is_main:
                save_main_evaluation(req.slug, result)
            else:
                save_additional_evaluation(req.slug, req.audio_url, result)

        return result
    except APIError:
        raise
    except Exception as e:
        logger.exception("Ошибка при оценке качества аудио")
        raise ExternalAPIError(message=str(e), service_name="Gemini")
