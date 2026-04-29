"""
Pixabay Videos API B-roll provider.

Docs: https://pixabay.com/api/docs/#api_search_videos
Бесплатно, лимит 100 запросов/мин.
"""
from __future__ import annotations

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

logger = logging.getLogger("broll.pixabay")

API_URL = "https://pixabay.com/api/videos/"


class PixabayProvider:
    name = "pixabay"
    kind = "stock"

    async def search(
        self,
        query: str,
        *,
        duration_sec: float,
        orientation: str = "portrait",
    ) -> Optional[ClipResult]:
        if not settings.pixabay_api_key:
            raise ProviderUnavailable("PIXABAY_API_KEY не задан в .env")

        params = {
            "key": settings.pixabay_api_key,
            "q": query,
            "per_page": 20,
            "video_type": "film",
            "safesearch": "true",
        }

        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(API_URL, params=params) as resp:
                    if resp.status == 400:
                        raise ProviderUnavailable("Pixabay: невалидный запрос или API-ключ")
                    if resp.status == 429:
                        raise ProviderError("Pixabay: превышен rate limit")
                    if resp.status != 200:
                        raise ProviderError(f"Pixabay HTTP {resp.status}")
                    data = await resp.json()
        except aiohttp.ClientError as e:
            raise ProviderError(f"Pixabay network error: {e}") from e

        hits = data.get("hits") or []
        if not hits:
            logger.info(f"Pixabay: ничего не найдено по {query!r}")
            return None

        best = self._pick_best(hits, duration_sec, orientation)
        if not best:
            return None

        return ClipResult(
            url=best["url"],
            duration=best["duration"],
            width=best["width"],
            height=best["height"],
            license="Pixabay",
            source=self.name,
            query=query,
            cost_usd=0.0,
        )

    @staticmethod
    def _pick_best(hits: list[dict], target_dur: float, orientation: str) -> Optional[dict]:
        # Pixabay videos.large/medium/small/tiny — выбираем large.
        scored: list[tuple[float, dict]] = []
        for h in hits:
            v_duration = float(h.get("duration", 0))
            videos = h.get("videos") or {}
            chosen = videos.get("large") or videos.get("medium") or videos.get("small")
            if not chosen or not chosen.get("url"):
                continue
            w = chosen.get("width") or 1080
            ht = chosen.get("height") or 1920
            # фильтр по ориентации (мягкий)
            if orientation == "portrait" and w > ht:
                continue
            if orientation == "landscape" and ht > w:
                continue
            score = abs(v_duration - target_dur)
            scored.append((score, {
                "url": chosen["url"],
                "duration": v_duration,
                "width": w,
                "height": ht,
            }))
        if not scored:
            # Если ничего не подошло по ориентации — попробуем без фильтра
            for h in hits:
                videos = h.get("videos") or {}
                chosen = videos.get("large") or videos.get("medium") or videos.get("small")
                if not chosen or not chosen.get("url"):
                    continue
                return {
                    "url": chosen["url"],
                    "duration": float(h.get("duration", 0)),
                    "width": chosen.get("width") or 1080,
                    "height": chosen.get("height") or 1920,
                }
            return None
        scored.sort(key=lambda x: x[0])
        return scored[0][1]
