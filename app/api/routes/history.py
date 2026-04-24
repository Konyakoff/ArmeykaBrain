"""История результатов: /api/history, /api/text/{slug}."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotFoundError
from app.db.database import get_recent_results, get_result_by_slug

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history")
async def get_history(tab: str = "text"):
    return {"history": get_recent_results(50, tab)}


@router.get("/text/{slug}")
async def get_result_api(slug: str):
    res = get_result_by_slug(slug)
    if res:
        return res
    raise NotFoundError("Результат не найден")
