"""
Luma Dream Machine B-roll provider.

API: https://docs.lumalabs.ai/docs/api
Pricing: ~$0.20 за 5-секундный 720p клип.
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

logger = logging.getLogger("broll.luma")

BASE_URL = "https://api.lumalabs.ai/dream-machine/v1/generations"

PRICE_USD = 0.20  # estimate per generation


class LumaProvider:
    name = "luma"
    kind = "ai"

    def __init__(self, *, max_wait_sec: int = 240, poll_interval: int = 8):
        self.max_wait_sec = max_wait_sec
        self.poll_interval = poll_interval

    async def search(
        self,
        query: str,
        *,
        duration_sec: float,
        orientation: str = "portrait",
    ) -> Optional[ClipResult]:
        if not settings.luma_api_key:
            raise ProviderUnavailable("LUMA_API_KEY не задан в .env")

        aspect = "9:16" if orientation == "portrait" else (
                 "1:1" if orientation == "square" else "16:9")

        headers = {
            "Authorization": f"Bearer {settings.luma_api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = {
            "prompt": query,
            "aspect_ratio": aspect,
            "loop": False,
        }

        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(BASE_URL, headers=headers, json=body) as resp:
                    if resp.status in (401, 403):
                        raise ProviderUnavailable("Luma: невалидный API-ключ")
                    if resp.status not in (200, 201, 202):
                        text = await resp.text()
                        raise ProviderError(f"Luma create HTTP {resp.status}: {text[:200]}")
                    gen = await resp.json()
        except aiohttp.ClientError as e:
            raise ProviderError(f"Luma network error: {e}") from e

        gen_id = gen.get("id")
        if not gen_id:
            raise ProviderError(f"Luma: id отсутствует в ответе: {gen}")

        url = await self._wait_for_generation(gen_id)
        if not url:
            return None

        w, h = (720, 1280) if orientation == "portrait" else ((720, 720) if orientation == "square" else (1280, 720))
        return ClipResult(
            url=url, duration=5.0,
            width=w, height=h,
            license="Luma",
            source=self.name,
            query=query,
            cost_usd=PRICE_USD,
        )

    async def _wait_for_generation(self, gen_id: str) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {settings.luma_api_key}",
            "Accept": "application/json",
        }
        elapsed = 0
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while elapsed < self.max_wait_sec:
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval
                async with session.get(f"{BASE_URL}/{gen_id}", headers=headers) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise ProviderError(f"Luma poll HTTP {resp.status}: {text[:200]}")
                    info = await resp.json()
                state = (info.get("state") or "").lower()
                if state == "completed":
                    assets = info.get("assets") or {}
                    return assets.get("video") or info.get("video_url")
                if state == "failed":
                    raise ProviderError(f"Luma: failed — {info.get('failure_reason', 'unknown')}")
        raise ProviderError(f"Luma: timeout после {self.max_wait_sec}с")
