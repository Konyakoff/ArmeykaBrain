"""
Pexels Videos API B-roll provider.

Docs: https://www.pexels.com/api/documentation/#videos
Бесплатно, лимит 200 запросов/час, 20000/месяц.
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

logger = logging.getLogger("broll.pexels")

API_URL = "https://api.pexels.com/videos/search"


class PexelsProvider:
    name = "pexels"
    kind = "stock"

    async def search(
        self,
        query: str,
        *,
        duration_sec: float,
        orientation: str = "portrait",
    ) -> Optional[ClipResult]:
        if not settings.pexels_api_key:
            raise ProviderUnavailable("PEXELS_API_KEY не задан в .env")

        params = {
            "query": query,
            "per_page": 15,
            "orientation": orientation if orientation in ("portrait", "landscape", "square") else "portrait",
            "size": "medium",
        }
        headers = {"Authorization": settings.pexels_api_key}

        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(API_URL, headers=headers, params=params) as resp:
                    if resp.status == 401:
                        raise ProviderUnavailable("Pexels: невалидный API-ключ")
                    if resp.status == 429:
                        raise ProviderError("Pexels: превышен rate limit")
                    if resp.status != 200:
                        raise ProviderError(f"Pexels HTTP {resp.status}")
                    data = await resp.json()
        except aiohttp.ClientError as e:
            raise ProviderError(f"Pexels network error: {e}") from e

        videos = data.get("videos") or []
        if not videos:
            logger.info(f"Pexels: ничего не найдено по {query!r}")
            return None

        # Выбираем лучший клип по длительности и разрешению
        best = self._pick_best(videos, duration_sec)
        if not best:
            return None

        return ClipResult(
            url=best["url"],
            duration=best["duration"],
            width=best["width"],
            height=best["height"],
            license="Pexels",
            source=self.name,
            query=query,
            cost_usd=0.0,
        )

    @staticmethod
    def _pick_best(videos: list[dict], target_dur: float) -> Optional[dict]:
        # Каждое видео имеет несколько вариантов разрешения в video_files.
        # Выбираем mp4 с разрешением >= 720p и продолжительностью близкой к целевой.
        scored: list[tuple[float, dict]] = []
        for v in videos:
            v_duration = float(v.get("duration", 0))
            files = [f for f in v.get("video_files", [])
                     if (f.get("file_type") or "").endswith("mp4")]
            if not files or v_duration < 1:
                continue
            # Берём файл с разрешением 720-1080p
            files.sort(key=lambda f: abs((f.get("height") or 0) - 1080))
            best_file = files[0]
            # Очки: чем ближе длительность к target, тем лучше
            score = abs(v_duration - target_dur)
            scored.append((score, {
                "url": best_file["link"],
                "duration": v_duration,
                "width": best_file.get("width") or 1080,
                "height": best_file.get("height") or 1920,
            }))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0])
        return scored[0][1]
