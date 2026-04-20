import os
import re
import time
import asyncio
import logging
import json
import html as _html
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

# Настраиваем логирование в файл (и в консоль)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("db/app.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("api")

from app.core.config import settings
from app.core.exceptions import APIError, NotFoundError, ExternalAPIError, ValidationError, api_error_handler, global_exception_handler
from app.services.data_loader import GEMINI_MODELS
from app.db.database import init_db, get_db_path, log_message, get_recent_results, get_result_by_slug, add_additional_audio, save_main_evaluation, save_additional_evaluation
from app.services.core import process_query_logic, process_upgrade_to_audio_logic
from app.services.elevenlabs_service import generate_audio, get_elevenlabs_voices, _fetch_elevenlabs_voices_from_api
from app.services.gemini_service import evaluate_audio_quality

# Глобальный сет для жестких ссылок на фоновые задачи (чтобы их не удалял GC)
background_tasks = set()

app = FastAPI(title="ArmeykaBrain API")

app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Настройка CORS, если фронтенд будет на другом домене (в нашем случае все на одном, но для безопасности)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене лучше указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Монтируем папку static для раздачи статических файлов (фронтенда)
app.mount("/static", StaticFiles(directory="static"), name="static")

_AVATAR_PREVIEW_DIR = os.path.join("static", "img", "avatars")
_AVATAR_ID_SAFE = re.compile(r"^[a-zA-Z0-9_-]+$")

templates = Jinja2Templates(directory="templates")


_AVATAR_FMT = {
    "16:9": {"key": "is_horizontal_friendly", "label": "16:9", "color": "#4f46e5"},
    "9:16": {"key": "is_vertical_friendly",   "label": "9:16", "color": "#059669"},
    "1:1":  {"key": "is_square_friendly",     "label": "1:1",  "color": "#d97706"},
}

@app.get("/api/avatars-html")
async def get_avatars_html(format: str = "16:9", tab: str = "public", show_all: str = "0"):
    """
    Публичные аватары → текстовый список с data-gender (надёжно, нет конфликтов с CSS).
    Приватные аватары → карточки с фото (их мало, изображения загружаются гарантированно).
    """
    fmt = _AVATAR_FMT.get(format, _AVATAR_FMT["16:9"])

    # ── Приватные: карточки с фото (мало аватаров, изображения всегда грузятся) ──
    if tab == "private":
        avatars = await get_heygen_private_avatars()
        if not avatars:
            return HTMLResponse(
                '<div style="padding:60px 20px;text-align:center;color:#9ca3af;font-size:14px;">'
                'Личные аватары не найдены</div>'
            )
        parts = []
        for a in avatars:
            aid      = a["avatar_id"]
            name     = _html.escape(a.get("avatar_name", aid))
            is_good  = bool(a.get(fmt["key"]))
            badge_bg = fmt["color"] if is_good else "#6b7280"
            badge_sym = "✓" if is_good else "~"
            img_url  = f"/static/img/avatars/{aid}.webp"
            parts.append(
                f'<div data-avatar-id="{_html.escape(aid)}" role="button" tabindex="0" '
                f'style="display:flex;flex-direction:column;border-radius:12px;cursor:pointer;'
                f'overflow:hidden;background:#fff;border:2px solid #e5e7eb;'
                f'box-shadow:0 1px 3px rgba(0,0,0,.06);">'
                f'<div style="height:140px;min-height:140px;background-color:#e5e7eb;'
                f"background-image:url('{img_url}');"
                f'background-size:cover;background-position:top center;position:relative;">'
                f'<div style="position:absolute;top:4px;right:4px;font-size:9px;font-weight:700;'
                f'padding:2px 5px;border-radius:4px;background:{badge_bg};color:#fff;">'
                f'{badge_sym}&nbsp;{fmt["label"]}</div></div>'
                f'<div style="padding:8px 6px;font-size:11px;font-weight:600;color:#374151;'
                f'text-align:center;min-height:2.75em;display:flex;align-items:center;'
                f'justify-content:center;">{name}</div>'
                f'</div>'
            )
        return HTMLResponse('\n'.join(parts))

    # ── Публичные: текстовый список (нет проблем с CSS/изображениями) ──────────
    all_av = await get_heygen_avatars()
    if show_all != "1":
        filtered = [a for a in all_av if a.get(fmt["key"])]
        avatars  = filtered if filtered else all_av
    else:
        avatars  = all_av

    if not avatars:
        return HTMLResponse(
            '<div style="padding:60px 20px;text-align:center;color:#9ca3af;font-size:14px;">'
            'Аватары не найдены</div>'
        )

    _GENDER_ICON = {"female": "♀", "male": "♂"}
    parts = []
    for a in avatars:
        aid       = a["avatar_id"]
        name      = _html.escape(a.get("avatar_name", aid))
        is_good   = bool(a.get(fmt["key"]))
        badge_bg  = fmt["color"] if is_good else "#9ca3af"
        badge_sym = "✓" if is_good else "~"
        gender    = (a.get("gender") or "unknown").lower()
        g_icon    = _GENDER_ICON.get(gender, "")
        g_color   = "#ec4899" if gender == "female" else ("#3b82f6" if gender == "male" else "#9ca3af")

        parts.append(
            f'<div data-avatar-id="{_html.escape(aid)}" data-gender="{gender}" '
            f'role="button" tabindex="0" '
            f'style="display:flex;align-items:center;gap:10px;padding:9px 14px;'
            f'border-bottom:1px solid #f3f4f6;cursor:pointer;background:#fff;"'
            f' onmouseover="if(!this.dataset.sel)this.style.background=\'#f9fafb\'"'
            f' onmouseout="if(!this.dataset.sel)this.style.background=\'#fff\'">'

            f'<span style="font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;'
            f'background:{badge_bg};color:#fff;white-space:nowrap;flex-shrink:0;">'
            f'{badge_sym}&nbsp;{fmt["label"]}</span>'

            f'<span style="font-size:13px;color:{g_color};flex-shrink:0;width:14px;'
            f'text-align:center;">{g_icon}</span>'

            f'<span style="font-size:13px;color:#374151;font-weight:500;flex:1;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{name}</span>'

            f'<span data-preview-id="{_html.escape(aid)}" '
            f'style="flex-shrink:0;color:#94a3b8;cursor:pointer;padding:4px 6px;'
            f'border-radius:6px;line-height:1;"'
            f' onmouseover="this.style.color=\'#F47920\';this.style.background=\'#fff7ed\'"'
            f' onmouseout="this.style.color=\'#94a3b8\';this.style.background=\'transparent\'"'
            f' title="Предпросмотр аватара">'
            f'<i class="fas fa-eye" style="pointer-events:none;font-size:12px;"></i></span>'
            f'</div>'
        )

    return HTMLResponse('\n'.join(parts))


@app.get("/api/avatar-preview/{avatar_id}")
async def get_avatar_preview(avatar_id: str):
    """Отдаёт локальный превью-кадр аватара HeyGen (webp). Надёжнее, чем полагаться на Tailwind в динамическом HTML."""
    if not _AVATAR_ID_SAFE.match(avatar_id):
        raise NotFoundError(message="Некорректный идентификатор аватара")
    path = os.path.join(_AVATAR_PREVIEW_DIR, f"{avatar_id}.webp")
    if not os.path.isfile(path):
        raise NotFoundError(message="Превью аватара не найдено")
    return FileResponse(path, media_type="image/webp")

# Модели Pydantic для валидации входных данных
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Текст вопроса")
    model: str = Field(default="gemini-3.1-pro-preview", description="Название модели")
    style: str = Field(default="telegram_yur", description="Стиль ответа")
    context_threshold: int = Field(default=70, ge=0, le=100, description="Порог контекста (%)")
    max_length: int = Field(default=4000, description="Максимальная длина ответа в символах")
    send_prompts: bool = Field(default=False, description="Возвращать ли тексты промптов")
    audio_duration: int = Field(default=30, ge=14, le=300, description="Длительность аудио в секундах")
    tab_type: str = Field(default="text", description="Тип вкладки (text или audio)")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs для озвучки")
    audio_wpm: int = Field(default=150, ge=100, le=250, description="Слов в минуту")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_style: float = Field(default=0.25, ge=0.0, le=1.0, description="Стиль (Style)")
    use_speaker_boost: bool = Field(default=True, description="Использовать Speaker Boost")
    audio_stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Stability")
    audio_similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity Boost")
    heygen_avatar_id: str = Field(default="Abigail_standing_office_front", description="ID аватара HeyGen")
    video_format: str = Field(default="16:9", description="Формат видео: 16:9, 9:16, 1:1")
    heygen_engine: str = Field(default="avatar_iv", description="Версия движка: avatar_iv, avatar_iii")
    avatar_style: str = Field(default="auto", description="Стиль кадрирования: auto | normal | closeUp | circle")
    custom_prompts: Optional[dict] = Field(default=None, description="Кастомные шаблоны промптов для текущего запроса")

class AudioRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Текст для озвучки")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_wpm: int = Field(default=150, ge=100, le=250, description="Скорость в словах в минуту")
    stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Stability")
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity Boost")
    style: float = Field(default=0.25, ge=0.0, le=1.0, description="Style")
    use_speaker_boost: bool = Field(default=True, description="Использовать Speaker Boost")
    slug: str = Field(default=None, description="Slug для привязки к результату")

class UpgradeAudioRequest(BaseModel):
    slug: str = Field(..., description="Slug результата для апгрейда")
    audio_duration: int = Field(default=60, ge=14, le=300, description="Длительность аудио в секундах")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs")
    audio_wpm: int = Field(default=150, ge=100, le=250, description="Скорость в словах в минуту")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_style: float = Field(default=0.25, ge=0.0, le=1.0, description="Style")
    use_speaker_boost: bool = Field(default=True, description="Speaker Boost")
    audio_stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Stability")
    audio_similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity Boost")
    generate_video: bool = Field(default=False, description="Создать также видео (Шаг 5)")
    heygen_avatar_id: str = Field(default="Abigail_standing_office_front", description="ID аватара HeyGen")
    video_format: str = Field(default="16:9", description="Формат видео: 16:9, 9:16, 1:1")
    heygen_engine: str = Field(default="avatar_iv", description="Версия движка: avatar_iv, avatar_iii")
    avatar_style: str = Field(default="auto", description="Стиль кадрирования: auto | normal | closeUp | circle")

class GenerateVideoRequest(BaseModel):
    slug: str = Field(..., description="Slug результата")
    audio_url: str = Field(..., description="Путь до аудиофайла")
    heygen_engine: str = Field(default="avatar_iv", description="Версия движка HeyGen")
    video_format: str = Field(default="16:9", description="Формат видео")
    heygen_avatar_id: str = Field(..., description="ID аватара HeyGen")
    avatar_style: str = Field(default="auto", description="Стиль кадрирования: auto | normal | closeUp | circle")
    is_main: bool = Field(default=True, description="Является ли это основным аудио")

class EvaluateRequest(BaseModel):
    audio_url: str = Field(..., description="Путь до аудиофайла")
    text: str = Field(..., description="Текст для озвучки")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    stability: float = Field(default=0.5, description="Stability")
    similarity_boost: float = Field(default=0.75, description="Similarity Boost")
    style: float = Field(default=0.25, description="Style")
    use_speaker_boost: bool = Field(default=True, description="Speaker Boost")
    slug: str = Field(default=None, description="Slug результата")
    is_main: bool = Field(default=True, description="Основное ли это аудио")

@app.on_event("startup")
async def startup_event():
    # Инициализация базы данных при старте
    init_db()
    print("API сервер запущен. База данных инициализирована.")

@app.get("/", response_class=HTMLResponse)
@app.get("/text", response_class=HTMLResponse)
@app.get("/audio", response_class=HTMLResponse)
@app.get("/video", response_class=HTMLResponse)
async def read_index(request: Request):
    # Возвращаем шаблон index.html
    return templates.TemplateResponse(request=request, name="index.html")

from app.core.prompt_manager import PromptManager

from app.services.heygen_service import get_heygen_avatars, get_heygen_private_avatars, check_video_status, _fetch_heygen_avatars_from_api, _fetch_heygen_private_avatars_from_api

@app.get("/api/video_status")
async def check_heygen_video(video_id: str):
    """
    Эндпоинт для проверки статуса видео
    """
    try:
        status_data = await check_video_status(video_id)
        # Если завершено, нужно сохранить в БД (или фронт это запросит, но лучше здесь обновить)
        # Для простоты фронт будет пулить и при успехе сам может вызвать endpoint или мы обновим прямо тут
        # Но чтобы обновить тут нужен slug. Пусть фронт шлет slug.
        return status_data
    except Exception as e:
        logger.error(f"Error checking video status: {e}")
        return {"status": "error", "error": str(e)}

@app.post("/api/update_video_result")
async def update_video_result(req: dict):
    from app.db.database import update_result_with_video_status, update_additional_video_url
    if "slug" in req and "video_url" in req:
        is_main = req.get("is_main", True)
        if is_main:
            update_result_with_video_status(req["slug"], req["video_url"])
        else:
            video_id = req.get("video_id")
            if video_id:
                update_additional_video_url(req["slug"], video_id, req["video_url"])
        return {"success": True}
    return {"success": False}

@app.get("/api/config")
async def get_config():
    """
    Возвращает доступные модели и стили для заполнения селектов на фронтенде
    """
    styles_data = PromptManager.get_styles()
    models = [{"id": m["model_name"], "name": m["model_name"]} for m in GEMINI_MODELS]
    styles = [{"id": s, "name": s} for s in styles_data.keys()]

    voices, avatars_raw, private_raw = await asyncio.gather(
        get_elevenlabs_voices(),
        get_heygen_avatars(),
        get_heygen_private_avatars(),
    )

    avatars = [
        {k: v for k, v in a.items() if not k.startswith("_")}
        for a in avatars_raw
    ]
    private_avatars = [
        {k: v for k, v in a.items() if not k.startswith("_")}
        for a in private_raw
    ]

    return {
        "models": models,
        "styles": styles,
        "voices": voices,
        "avatars": avatars,
        "private_avatars": private_avatars,
        "default_model": "gemini-3.1-pro-preview",
        "default_style": "telegram_yur",
        "default_voice": "FGY2WhTYpPnroxEErjIq",
        "default_avatar": "Abigail_standing_office_front"
    }

def _check_admin_password(password: Optional[str]) -> bool:
    """Проверяет пароль администратора."""
    return password == settings.admin_password


@app.get("/api/prompts")
async def get_prompts():
    """Возвращает текущие шаблоны промптов для редактора."""
    from app.core.prompt_manager import PromptManager as PM
    styles = PM.get_styles()
    audio = PM.get_audio_prompts()

    # Для step3 возвращаем все ключи кроме служебных (evaluation)
    step3_keys = {k: v for k, v in audio.items() if k != "evaluation"}

    prompts = {
        "step2_style": {k: v for k, v in styles.items()},
        "step3": step3_keys,
    }

    return JSONResponse(content={"prompts": prompts})


class SavePromptRequest(BaseModel):
    target: str
    content: str
    style_key: Optional[str] = None
    password: Optional[str] = None


class CreatePromptRequest(BaseModel):
    target: str
    name: str
    content: str
    password: Optional[str] = None


class DeletePromptRequest(BaseModel):
    target: str
    name: str
    password: Optional[str] = None


@app.post("/api/prompts/save")
async def save_prompt(req: SavePromptRequest):
    """Сохраняет изменённый промпт на диск (требует пароль админа)."""
    if not _check_admin_password(req.password):
        return JSONResponse(content={"ok": False, "error": "Неверный пароль администратора"}, status_code=403)
    from app.core.prompt_manager import PromptManager as PM
    try:
        PM.save_prompt(req.target, req.content, req.style_key)
        return JSONResponse(content={"ok": True})
    except ValueError as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/prompts/create")
async def create_prompt(req: CreatePromptRequest):
    """Создаёт новый именованный промпт (требует пароль админа)."""
    if not _check_admin_password(req.password):
        return JSONResponse(content={"ok": False, "error": "Неверный пароль администратора"}, status_code=403)
    from app.core.prompt_manager import PromptManager as PM
    try:
        PM.create_prompt(req.target, req.name, req.content)
        return JSONResponse(content={"ok": True})
    except ValueError as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/prompts/delete")
async def delete_prompt(req: DeletePromptRequest):
    """Удаляет промпт по имени (требует пароль админа)."""
    if not _check_admin_password(req.password):
        return JSONResponse(content={"ok": False, "error": "Неверный пароль администратора"}, status_code=403)
    from app.core.prompt_manager import PromptManager as PM
    try:
        PM.delete_prompt(req.target, req.name)
        return JSONResponse(content={"ok": True})
    except ValueError as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/query")
async def process_user_query(req: QueryRequest):
    """
    Основной эндпоинт для обработки вопроса (с поддержкой фоновой потоковой передачи)
    """
    logger.info(f"Получен запрос: модель={req.model}, стиль={req.style}, текст='{req.question[:50]}...'")
    
    # Логируем входящий запрос
    log_message("web_user", "web_interface", "in", req.question)
    
    queue = asyncio.Queue()
    
    # Запускаем фоновую задачу, которая будет жить даже если клиент отвалится
    task = asyncio.create_task(
        process_query_logic(
            queue=queue,
            question=req.question,
            model=req.model,
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
            custom_prompts=req.custom_prompts or {}
        )
    )
    # Сохраняем жесткую ссылку, чтобы сборщик мусора не удалил задачу
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    
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

    return EventSourceResponse(generator())

@app.post("/api/upgrade_to_audio")
async def upgrade_to_audio(req: UpgradeAudioRequest):
    """
    Эндпоинт для апгрейда текстового результата до аудио-сценария и озвучки.
    """
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
            previous_total_cost=result_data.get("total_stats", {}).get("total_cost", 0.0) if isinstance(result_data.get("total_stats"), dict) else 0.0,
            generate_video=req.generate_video,
            heygen_avatar_id=req.heygen_avatar_id,
            video_format=req.video_format,
            heygen_engine=req.heygen_engine,
            avatar_style=req.avatar_style if hasattr(req, 'avatar_style') else "auto"
        )
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    
    async def generator():
        try:
            while True:
                chunk = await queue.get()
                if chunk.get("step") == "done":
                    yield {"data": json.dumps(chunk, ensure_ascii=False)}
                    break
                elif chunk.get("step") == "error":
                    yield {"data": json.dumps(chunk, ensure_ascii=False)}
                    break
                yield {"data": json.dumps(chunk, ensure_ascii=False)}
        except asyncio.CancelledError:
            logger.info("Клиент отключился, но апгрейд аудио продолжается.")
        except Exception as e:
            logger.exception("Непредвиденная ошибка генератора апгрейда")
            yield {"data": json.dumps({"step": "error", "message": f"Внутренняя ошибка: {str(e)}"}, ensure_ascii=False)}

    return EventSourceResponse(generator())

@app.post("/api/generate_audio_only")
async def process_generate_audio_only(req: AudioRequest):
    """
    Эндпоинт для генерации дополнительного аудио из готового текста
    """
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
            use_speaker_boost=req.use_speaker_boost
        )
        
        # Расчет стоимости
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
            "cost": eleven_cost
        }
        
        # Сохраняем в БД, если передан slug
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
            "cost": eleven_cost
        }
    except APIError:
        raise
    except Exception as e:
        logger.exception("Ошибка при генерации дополнительного аудио")
        raise ExternalAPIError(message=f"Ошибка генерации аудио: {str(e)}", service_name="ElevenLabs")

@app.post("/api/generate_video_only")
async def process_generate_video_only(req: GenerateVideoRequest):
    """
    Эндпоинт для генерации дополнительного или основного видео из аудио
    """
    from app.services.heygen_service import generate_video_from_audio, calculate_heygen_cost
    from app.db.database import update_result_with_video, get_result_by_slug
    try:
        host_url = "https://armeykabrain.net"
        public_audio_url = req.audio_url if req.audio_url.startswith("http") else f"{host_url}{req.audio_url}"
        
        step5_video_id = await generate_video_from_audio(
            avatar_id=req.heygen_avatar_id,
            audio_url=public_audio_url,
            title="ArmeykaBrain Video",
            video_format=req.video_format,
            heygen_engine=req.heygen_engine,
            avatar_style=req.avatar_style
        )
        
        # Получаем duration_sec для подсчета стоимости. 
        # Если это доп. аудио, нам надо найти его в базе.
        # Если это основное, мы можем взять из step4_stats.
        duration_sec = 60 # дефолт
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
                        # Попробуем вытащить wpm и char_count, если есть. Иначе примерно 60сек.
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
            "started_at": int(time.time())
        }
        
        # Сохраняем в БД как pending
        if req.is_main:
            update_result_with_video(req.slug, step5_video_id, json.dumps(step5_stats, ensure_ascii=False))
        else:
            from app.db.database import save_additional_video_stats
            save_additional_video_stats(req.slug, req.audio_url, step5_video_id, step5_stats)
            
        return {
            "success": True, 
            "video_id": step5_video_id,
            "stats": step5_stats
        }
    except Exception as e:
        logger.exception("Ошибка при генерации видео")
        raise ExternalAPIError(message=f"Ошибка генерации видео: {str(e)}", service_name="HeyGen")

@app.post("/api/evaluate_audio")
async def evaluate_audio(req: EvaluateRequest):
    """
    Оценивает качество сгенерированного аудио через Gemini 3.1 Pro Preview
    """
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
            "use_speaker_boost": req.use_speaker_boost
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

@app.get("/api/db/download")
async def download_db():
    """
    Эндпоинт для скачивания базы данных
    """
    db_path = get_db_path()
    if os.path.exists(db_path):
        return FileResponse(
            path=db_path, 
            filename="dialogs.db", 
            media_type="application/octet-stream"
        )
    else:
        raise NotFoundError("База данных не найдена")


# --- Обновление внешнего кэша ---
_cache_update_status = {
    "running": False,
    "last_updated_at": None,  # ISO timestamp
    "error": None,
}

def _get_cache_last_updated() -> Optional[str]:
    """Определяет время последнего обновления по mtime кэш-файлов."""
    import os as _os
    files = [
        "db/heygen_avatars_cache.json",
        "db/heygen_private_avatars_cache.json",
        "db/elevenlabs_voices_cache.json",
    ]
    mtimes = []
    for f in files:
        if _os.path.exists(f):
            mtimes.append(_os.path.getmtime(f))
    if not mtimes:
        return None
    import datetime
    ts = min(mtimes)  # берём самый старый, чтобы не вводить в заблуждение
    return datetime.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


@app.get("/api/cache/status")
async def get_cache_status():
    """Возвращает статус обновления внешнего кэша."""
    return {
        "running": _cache_update_status["running"],
        "last_updated_at": _cache_update_status["last_updated_at"] or _get_cache_last_updated(),
        "error": _cache_update_status["error"],
    }


@app.post("/api/cache/refresh")
async def refresh_cache():
    """Запускает фоновое обновление всех внешних кэшей (HeyGen + ElevenLabs)."""
    if _cache_update_status["running"]:
        return {"ok": False, "message": "Обновление уже выполняется"}

    async def _do_refresh():
        _cache_update_status["running"] = True
        _cache_update_status["error"] = None
        errors = []
        try:
            results = await asyncio.gather(
                _fetch_heygen_avatars_from_api(),
                _fetch_heygen_private_avatars_from_api(),
                _fetch_elevenlabs_voices_from_api(),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    errors.append(str(r))
        except Exception as e:
            errors.append(str(e))
        finally:
            import datetime
            _cache_update_status["running"] = False
            _cache_update_status["last_updated_at"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
            if errors:
                _cache_update_status["error"] = "; ".join(errors)

    task = asyncio.create_task(_do_refresh())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    return {"ok": True, "message": "Обновление запущено"}

@app.get("/api/history")
async def get_history(tab: str = "text"):
    """
    Эндпоинт для получения истории запросов
    """
    return {"history": get_recent_results(50, tab)}

@app.get("/api/text/{slug}")
async def get_result_api(slug: str):
    """
    Эндпоинт для получения конкретного результата
    """
    res = get_result_by_slug(slug)
    if res:
        return res
    raise NotFoundError("Результат не найден")

@app.get("/text/{slug}", response_class=HTMLResponse)
async def view_result_page(request: Request, slug: str):
    return templates.TemplateResponse(request=request, name="result.html", context={"slug": slug})


# ─────────────────────────────────────────────────────────────────────────────
# TREE API
# ─────────────────────────────────────────────────────────────────────────────

from app.db.database import (
    get_tree_nodes, get_tree_node, update_tree_node_title,
    delete_tree_node_cascade, migrate_saved_result_to_tree,
    update_tree_node_evaluation, update_tree_node_stats
)
from app.services.tree_service import dispatch_generate, _generate_timecodes_background


class GenerateNodeRequest(BaseModel):
    target_type: str = Field(..., description="script | audio | video")
    params: dict = Field(default_factory=dict)


class RenamNodeRequest(BaseModel):
    title: str


@app.get("/api/tree/{slug}")
async def get_tree(slug: str):
    """Возвращает все узлы дерева. При первом обращении мигрирует из SavedResult."""
    nodes = get_tree_nodes(slug)
    if not nodes:
        # Автоматическая миграция из старой структуры
        result_data = get_result_by_slug(slug)
        if not result_data:
            raise NotFoundError("Результат не найден")
        migrate_saved_result_to_tree(slug, result_data)
        nodes = get_tree_nodes(slug)

    result_data = get_result_by_slug(slug)
    return {
        "slug": slug,
        "question": result_data["question"] if result_data else "",
        "tab_type": result_data["tab_type"] if result_data else "text",
        "timestamp": result_data["timestamp"] if result_data else "",
        "nodes": nodes,
    }


@app.get("/api/tree/node/{node_id}")
async def get_tree_node_api(node_id: str):
    node = get_tree_node(node_id)
    if not node:
        raise NotFoundError("Узел не найден")
    return node


@app.patch("/api/tree/node/{node_id}/title")
async def rename_node(node_id: str, req: RenamNodeRequest):
    ok = update_tree_node_title(node_id, req.title)
    if not ok:
        raise NotFoundError("Узел не найден")
    return {"ok": True}


@app.delete("/api/tree/node/{node_id}")
async def delete_node(node_id: str):
    node = get_tree_node(node_id)
    if not node:
        raise NotFoundError("Узел не найден")
    if node["node_type"] == "article":
        raise ValidationError("Корневой узел нельзя удалить")
    ok = delete_tree_node_cascade(node_id)
    return {"ok": ok}


@app.patch("/api/tree/node/{node_id}/evaluation")
async def save_node_evaluation(node_id: str, req: dict):
    ok = update_tree_node_evaluation(node_id, req)
    return {"ok": ok}


@app.post("/api/tree/node/{node_id}/timecodes")
async def generate_node_timecodes(node_id: str):
    """Ручной запуск генерации таймкодов Deepgram для аудио-узла."""
    node = get_tree_node(node_id)
    if not node:
        raise NotFoundError("Узел не найден")
    if node.get("node_type") != "audio":
        raise ValidationError("Таймкоды поддерживаются только для аудио-узлов")
    st = node.get("stats_json") or {}
    if st.get("timecodes_json_url"):
        return {"ok": False, "message": "Таймкоды уже сгенерированы"}
    audio_url = node.get("content_url_original") or node.get("content_url")
    if not audio_url:
        raise ValidationError("Аудио-файл не найден в узле")

    task = asyncio.create_task(_generate_timecodes_background(node_id, audio_url))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    return {"ok": True, "message": "Генерация таймкодов запущена"}


@app.post("/api/tree/{slug}/node/{parent_node_id}/generate")
async def generate_node(slug: str, parent_node_id: str, req: GenerateNodeRequest):
    """
    SSE-эндпоинт генерации нового дочернего узла.
    События: node_created, step N, done / error
    """
    queue = asyncio.Queue()

    task = asyncio.create_task(
        dispatch_generate(queue, slug, parent_node_id, req.target_type, req.params)
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    async def generator():
        try:
            while True:
                chunk = await queue.get()
                yield {"data": json.dumps(chunk, ensure_ascii=False)}
                if chunk.get("step") in ("done", "error"):
                    break
        except asyncio.CancelledError:
            logger.info("Tree generate client disconnected, background continues")
        except Exception as e:
            yield {"data": json.dumps({"step": "error", "message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(generator())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)