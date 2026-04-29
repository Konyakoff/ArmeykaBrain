"""
Runway Gen-4 Turbo B-roll provider.

API: https://docs.dev.runwayml.com/api/

Note: Runway image_to_video требует начальный кадр. Для текстового
B-roll-промпта мы сначала генерируем изображение через Gemini (или используем
дефолтный плейсхолдер), а затем конвертируем в видео. Для упрощения сейчас
поддерживаем text_to_video через эндпоинт `text_to_video` (если/когда будет
доступен) — иначе возвращаем ProviderUnavailable.

Pricing: ~$0.05/sec → ~$0.25 за 5-сек клип.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from app.core.config import settings
from app.services.broll_providers.base import (
    BrollProvider,
    ClipResult,
    ProviderError,
    ProviderUnavailable,
)

logger = logging.getLogger("broll.runway")

BASE_URL = "https://api.dev.runwayml.com/v1"
RUNWAY_VERSION = "2024-11-06"

PRICE_PER_SEC_USD = 0.05


class RunwayProvider:
    name = "runway"
    kind = "ai"

    def __init__(self, model: str | None = None, *, max_wait_sec: int = 240, poll_interval: int = 6):
        self._model = model or "gen4.5"
        self.max_wait_sec = max_wait_sec
        self.poll_interval = poll_interval

    async def search(
        self,
        query: str,
        *,
        duration_sec: float,
        orientation: str = "portrait",
    ) -> Optional[ClipResult]:
        if not settings.runway_api_key:
            raise ProviderUnavailable("RUNWAY_API_KEY не задан в .env")

        # Runway accepts duration: 5 or 10 seconds
        dur = 10 if duration_sec >= 7.5 else 5
        
        # Determine ratio based on model
        if "gen4.5" in self._model:
            ratio = "720:1280" if orientation == "portrait" else "1280:720"
            w, h = (720, 1280) if orientation == "portrait" else (1280, 720)
        else:
            ratio = "768:1280" if orientation == "portrait" else ("960:960" if orientation == "square" else "1280:768")
            w, h = (768, 1280) if orientation == "portrait" else ((960, 960) if orientation == "square" else (1280, 768))

        headers = {
            "Authorization": f"Bearer {settings.runway_api_key}",
            "X-Runway-Version": RUNWAY_VERSION,
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "promptText": query,
            "duration": dur,
            "ratio": ratio,
        }

        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Endpoint: text_to_video (newer)
                async with session.post(f"{BASE_URL}/text_to_video", headers=headers, json=body) as resp:
                    if resp.status in (401, 403):
                        raise ProviderUnavailable("Runway: невалидный API-ключ или нет доступа")
                    if resp.status == 404:
                        raise ProviderUnavailable("Runway: text_to_video endpoint недоступен (нужен image_to_video)")
                    if resp.status != 200 and resp.status != 201 and resp.status != 202:
                        text = await resp.text()
                        raise ProviderError(f"Runway create HTTP {resp.status}: {text[:200]}")
                    task = await resp.json()
        except aiohttp.ClientError as e:
            raise ProviderError(f"Runway network error: {e}") from e

        task_id = task.get("id")
        if not task_id:
            raise ProviderError(f"Runway: task без id: {task}")

        url = await self._wait_for_task(task_id)
        if not url:
            return None

        return ClipResult(
            url=url, duration=float(dur),
            width=w, height=h,
            license="Runway",
            source=self.name,
            query=query,
            cost_usd=round(dur * PRICE_PER_SEC_USD, 4),
        )

    async def _wait_for_task(self, task_id: str) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {settings.runway_api_key}",
            "X-Runway-Version": RUNWAY_VERSION,
        }
        elapsed = 0
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while elapsed < self.max_wait_sec:
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval
                async with session.get(f"{BASE_URL}/tasks/{task_id}", headers=headers) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise ProviderError(f"Runway poll HTTP {resp.status}: {text[:200]}")
                    info = await resp.json()
                status = (info.get("status") or "").upper()
                if status == "SUCCEEDED":
                    out = info.get("output") or []
                    if isinstance(out, list) and out:
                        return out[0]
                    if isinstance(out, dict):
                        return out.get("url") or out.get("uri")
                    return None
                if status in ("FAILED", "CANCELLED"):
                    raise ProviderError(f"Runway: статус {status}: {info.get('failure', '')}")
        raise ProviderError(f"Runway: timeout после {self.max_wait_sec}с")
