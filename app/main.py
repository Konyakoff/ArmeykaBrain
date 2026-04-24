"""ArmeykaBrain FastAPI app — entrypoint.

Маршруты разделены по router-модулям в app/api/routes/* (PR3).
Глобальное состояние (background_tasks, active_streams) вынесено
в app/core/state.py.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("db/app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("api")

from app.core.exceptions import (
    APIError,
    api_error_handler,
    global_exception_handler,
)
from app.core.state import background_tasks, active_streams  # noqa: F401  (обратная совместимость импорта)
from app.db.database import init_db

from app.api.routes import pages, query, tree, prompts, history, meta

app = FastAPI(title="ArmeykaBrain API")

app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(Exception, global_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup_event():
    init_db()
    print("API сервер запущен. База данных инициализирована.")


for _r in (pages, query, tree, prompts, history, meta):
    app.include_router(_r.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
