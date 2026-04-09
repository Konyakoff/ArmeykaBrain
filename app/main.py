import os
import asyncio
import logging
import json
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
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
from app.core.exceptions import APIError, NotFoundError, ExternalAPIError, api_error_handler, global_exception_handler
from app.services.data_loader import GEMINI_MODELS
from app.db.database import init_db, get_db_path, log_message, get_recent_results, get_result_by_slug, add_additional_audio, save_main_evaluation, save_additional_evaluation
from app.services.core import process_query_logic
from app.services.elevenlabs_service import generate_audio, get_elevenlabs_voices
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

templates = Jinja2Templates(directory="templates")

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
    audio_wpm: int = Field(default=175, ge=100, le=250, description="Слов в минуту")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_style: float = Field(default=0.25, ge=0.0, le=1.0, description="Стиль (Style)")
    use_speaker_boost: bool = Field(default=True, description="Использовать Speaker Boost")

class AudioRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Текст для озвучки")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_wpm: int = Field(default=175, ge=100, le=250, description="Скорость в словах в минуту")
    stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Stability")
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity Boost")
    style: float = Field(default=0.25, ge=0.0, le=1.0, description="Style")
    use_speaker_boost: bool = Field(default=True, description="Использовать Speaker Boost")
    slug: str = Field(default=None, description="Slug для привязки к результату")

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
async def read_index(request: Request):
    # Возвращаем шаблон index.html
    return templates.TemplateResponse(request=request, name="index.html")

from app.core.prompt_manager import PromptManager

@app.get("/api/config")
async def get_config():
    """
    Возвращает доступные модели и стили для заполнения селектов на фронтенде
    """
    styles_data = PromptManager.get_styles()
    models = [{"id": m["model_name"], "name": m["model_name"]} for m in GEMINI_MODELS]
    styles = [{"id": s, "name": s} for s in styles_data.keys()]
    voices = await get_elevenlabs_voices()
    
    return {
        "models": models,
        "styles": styles,
        "voices": voices,
        "default_model": "gemini-3.1-pro-preview",
        "default_style": "telegram_yur",
        "default_voice": "FGY2WhTYpPnroxEErjIq"
    }

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
            use_speaker_boost=req.use_speaker_boost
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
    """
    Страница отдельного результата
    """
    return templates.TemplateResponse(request=request, name="result.html", context={"slug": slug})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)