"""
Creatomate API service — программный видео-монтаж через RenderScript JSON.

API Reference: https://creatomate.com/docs/api/quick-start/create-a-video-by-render-script
Workflow: POST /v2/renders → polling GET /v1/renders/{id} → готовый MP4.

Цена в кредитах: (W * H * FPS * duration_sec) / 100_000_000 (минимум 1).
1 кредит ≈ $0.0041 (Growth tier 10K credits / $41).
"""
import asyncio
import logging
import math
import aiohttp

from app.core.config import settings

logger = logging.getLogger("creatomate_service")

BASE_URL_RENDER = "https://api.creatomate.com/v2/renders"
BASE_URL_STATUS = "https://api.creatomate.com/v1/renders"

USD_PER_CREDIT = 0.0041


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.creatomate_api_key}",
        "Content-Type": "application/json",
    }


def calculate_credits(width: int, height: int, fps: int, duration_sec: float) -> int:
    """
    Формула Creatomate: width * height * fps * duration / 100M, округление вверх, минимум 1.
    """
    if width <= 0 or height <= 0 or fps <= 0 or duration_sec <= 0:
        return 1
    raw = (width * height * fps * duration_sec) / 100_000_000.0
    return max(1, math.ceil(raw))


def calculate_cost_usd(credits: int) -> float:
    return round(credits * USD_PER_CREDIT, 4)


async def create_render(render_script: dict, *, output_format: str = "mp4") -> dict:
    """
    POST /v2/renders. Возвращает список render-объектов (Creatomate возвращает массив).
    Берём первый элемент для одиночного рендера.
    """
    if not settings.creatomate_api_key:
        raise Exception("CREATOMATE_API_KEY не задан в .env")

    payload = dict(render_script)
    payload.setdefault("output_format", output_format)

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(BASE_URL_RENDER, headers=_headers(), json=payload) as resp:
            data = await resp.json()
            if resp.status not in (200, 201, 202):
                err = data.get("message") if isinstance(data, dict) else str(data)
                raise Exception(f"Creatomate create_render error ({resp.status}): {err}")
            if isinstance(data, list):
                if not data:
                    raise Exception("Creatomate вернул пустой массив рендеров")
                first = data[0]
            elif isinstance(data, dict):
                first = data
            else:
                raise Exception(f"Creatomate: неожиданный формат ответа {type(data).__name__}")
            logger.info(f"Creatomate render created: id={first.get('id')}, status={first.get('status')}")
            return first


async def get_render(render_id: str) -> dict:
    """GET /v1/renders/{id}. Возвращает полный объект рендера со status и url."""
    if not settings.creatomate_api_key:
        raise Exception("CREATOMATE_API_KEY не задан в .env")

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{BASE_URL_STATUS}/{render_id}", headers=_headers()) as resp:
            data = await resp.json()
            if resp.status != 200:
                err = data.get("message") if isinstance(data, dict) else str(data)
                raise Exception(f"Creatomate get_render error ({resp.status}): {err}")
            return data


async def wait_for_render(
    render_id: str,
    *,
    interval_sec: int = 5,
    max_attempts: int = 360,
) -> dict:
    """
    Опрашивает статус рендера до завершения.
    Возвращает финальный объект (status='succeeded' или 'failed').
    """
    last = None
    for attempt in range(max_attempts):
        await asyncio.sleep(interval_sec)
        last = await get_render(render_id)
        st = (last.get("status") or "").lower()
        if st in ("succeeded", "completed"):
            return last
        if st in ("failed", "cancelled", "canceled"):
            err = last.get("error_message") or last.get("error") or "unknown error"
            raise Exception(f"Creatomate render failed: {err}")
        if attempt % 6 == 5:
            logger.info(f"Creatomate render {render_id}: status={st}, attempt={attempt+1}")
    raise Exception(f"Creatomate render timeout ({max_attempts*interval_sec}s)")
