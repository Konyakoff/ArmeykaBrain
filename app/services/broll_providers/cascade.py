"""
CascadeProvider — пробует несколько провайдеров по очереди (fallback).
Используется для "pexels_pixabay" и аналогичных составных режимов.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.broll_providers.base import (
    BrollProvider,
    ClipResult,
    ProviderError,
    ProviderUnavailable,
)

logger = logging.getLogger("broll.cascade")


class CascadeProvider:
    """Wraps several providers; returns first non-empty result."""

    kind = "stock"  # допущение: каскад используется только для стоков

    def __init__(self, providers: list[BrollProvider], *, name: str = "cascade"):
        self.providers = providers
        self.name = name
        # Если хотя бы один AI — режим становится 'ai'
        if any(p.kind == "ai" for p in providers):
            self.kind = "ai"

    async def search(
        self,
        query: str,
        *,
        duration_sec: float,
        orientation: str = "portrait",
    ) -> Optional[ClipResult]:
        last_err: Optional[Exception] = None
        for prov in self.providers:
            try:
                clip = await prov.search(query, duration_sec=duration_sec, orientation=orientation)
            except ProviderUnavailable as e:
                logger.info(f"Cascade: {prov.name} недоступен: {e}")
                last_err = e
                continue
            except ProviderError as e:
                logger.warning(f"Cascade: {prov.name} ошибка: {e}")
                last_err = e
                continue
            if clip:
                return clip
        if last_err and not any(self._is_skipped(p) for p in self.providers):
            # Если все упали с ошибкой и ни один не выдал — пробросим последнюю
            logger.warning(f"Cascade: все провайдеры не нашли клип для {query!r}")
        return None

    @staticmethod
    def _is_skipped(p: BrollProvider) -> bool:
        return False
