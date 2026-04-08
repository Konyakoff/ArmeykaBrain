import os
import asyncio
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

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

# Загружаем переменные окружения ДО импорта остальных модулей
load_dotenv()

from data_loader import GEMINI_MODELS
from database import init_db, get_db_path, log_message, get_recent_results, get_result_by_slug, add_additional_audio
from core import process_query_stream
from elevenlabs_service import generate_audio, get_elevenlabs_voices

app = FastAPI(title="ArmeykaBrain API")

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

class AudioRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Текст для озвучки")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_wpm: int = Field(default=175, ge=100, le=250, description="Скорость в словах в минуту")
    stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Stability")
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity Boost")
    slug: str = Field(default=None, description="Slug для привязки к результату")

@app.on_event("startup")
async def startup_event():
    # Инициализация базы данных при старте
    init_db()
    print("API сервер запущен. База данных инициализирована.")

@app.get("/")
async def read_index():
    # Перенаправляем корневой запрос на index.html
    return FileResponse("static/index.html")

import json

def get_styles():
    with open("styles.json", "r", encoding="utf-8") as f:
        return json.load(f)

@app.get("/api/config")
async def get_config():
    """
    Возвращает доступные модели и стили для заполнения селектов на фронтенде
    """
    styles_data = get_styles()
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
    Основной эндпоинт для обработки вопроса (с поддержкой потоковой передачи)
    """
    logger.info(f"Получен запрос: модель={req.model}, стиль={req.style}, текст='{req.question[:50]}...'")
    
    # Логируем входящий запрос
    log_message("web_user", "web_interface", "in", req.question)
    
    async def generator():
        try:
            async for chunk in process_query_stream(
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
                elevenlabs_voice=req.elevenlabs_voice
            ):
                if chunk.get("step") == "done":
                    log_message("web_user", "web_interface", "out", chunk["result"]["answer"])
                    logger.info("Запрос успешно обработан")
                elif chunk.get("step") == "error":
                    log_message("web_user", "web_interface", "out", chunk["message"])
                    logger.error(f"Ошибка при обработке: {chunk['message']}")
                    
                yield json.dumps(chunk, ensure_ascii=False) + "\n"
        except Exception as e:
            logger.exception("Непредвиденная ошибка генератора")
            yield json.dumps({"step": "error", "message": f"Внутренняя ошибка: {str(e)}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(generator(), media_type="application/x-ndjson")

@app.post("/api/generate_audio_only")
async def process_generate_audio_only(req: AudioRequest):
    """
    Эндпоинт для генерации дополнительного аудио из готового текста
    """
    try:
        speed = req.audio_wpm / 150.0
        audio_url = await generate_audio(
            text=req.text,
            model_id=req.elevenlabs_model,
            voice_id=req.elevenlabs_voice,
            speed=speed,
            stability=req.stability,
            similarity_boost=req.similarity_boost
        )
        
        # Расчет стоимости
        char_count = len(req.text)
        if "turbo" in req.elevenlabs_model or "flash" in req.elevenlabs_model:
            eleven_cost = (char_count / 1000) * 0.15
        else:
            eleven_cost = (char_count / 1000) * 0.30
            
        audio_data = {
            "audio_url": audio_url,
            "speed": speed,
            "wpm": req.audio_wpm,
            "model": req.elevenlabs_model,
            "voice": req.elevenlabs_voice,
            "stability": req.stability,
            "similarity_boost": req.similarity_boost,
            "cost": eleven_cost
        }
        
        # Сохраняем в БД, если передан slug
        if req.slug:
            add_additional_audio(req.slug, audio_data)
            
        return {
            "success": True, 
            "audio_url": audio_url, 
            "speed": speed, 
            "wpm": req.audio_wpm, 
            "model": req.elevenlabs_model,
            "voice": req.elevenlabs_voice,
            "stability": req.stability,
            "similarity_boost": req.similarity_boost,
            "cost": eleven_cost
        }
    except Exception as e:
        logger.exception("Ошибка при генерации дополнительного аудио")
        raise HTTPException(status_code=500, detail=f"Ошибка генерации аудио: {str(e)}")

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
        raise HTTPException(status_code=404, detail="База данных не найдена")

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
    raise HTTPException(status_code=404, detail="Результат не найден")

@app.get("/text/{slug}")
async def view_result_page(slug: str):
    """
    Страница отдельного результата
    """
    return FileResponse("static/result.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)