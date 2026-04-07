import os
import asyncio
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
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
from database import init_db, get_db_path, log_message
from core import process_query

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
    
    return {
        "models": models,
        "styles": styles,
        "default_model": "gemini-3.1-pro-preview",
        "default_style": "telegram_yur"
    }

@app.post("/api/query")
async def process_user_query(req: QueryRequest):
    """
    Основной эндпоинт для обработки вопроса
    """
    logger.info(f"Получен запрос: модель={req.model}, стиль={req.style}, текст='{req.question[:50]}...'")
    
    # Логируем входящий запрос (используем ID 0 для web-интерфейса или можно добавить IP)
    log_message("web_user", "web_interface", "in", req.question)
    
    try:
        # Вызываем ядро
        result = await process_query(
            question=req.question,
            model=req.model,
            style=req.style,
            context_threshold=req.context_threshold,
            send_prompts=req.send_prompts,
            max_length=req.max_length
        )
        
        if not result.get("success"):
            error_text = result.get("error", "Неизвестная ошибка")
            logger.error(f"Ошибка при обработке: {error_text}")
            log_message("web_user", "web_interface", "out", error_text)
            raise HTTPException(status_code=500, detail=error_text)
            
        # Логируем ответ
        logger.info("Запрос успешно обработан")
        log_message("web_user", "web_interface", "out", result["answer"])
        
        return JSONResponse(content=result)
        
    except Exception as e:
        logger.exception("Непредвиденная ошибка при обработке запроса")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)