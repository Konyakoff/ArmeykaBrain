"""Базовые типы и протокол для B-roll провайдеров."""
from __future__ import annotations

from typing import Literal, Optional, Protocol, TypedDict, runtime_checkable


class ClipResult(TypedDict, total=False):
    url: str               # прямой URL видео-файла (mp4)
    duration: float        # длительность в секундах
    width: int
    height: int
    license: str           # 'pexels', 'pixabay', 'CC0', etc.
    source: str            # имя провайдера: 'pexels', 'veo', ...
    query: str             # исходный запрос/промпт
    cost_usd: float        # 0.0 для стоков, >0 для AI


class ProviderError(Exception):
    """Любая ошибка при обращении к провайдеру B-roll (сеть, лимит, формат)."""


class ProviderUnavailable(ProviderError):
    """Провайдер не настроен (нет API-ключа) или не существует."""


@runtime_checkable
class BrollProvider(Protocol):
    name: str
    kind: Literal["stock", "ai"]

    async def search(
        self,
        query: str,
        *,
        duration_sec: float,
        orientation: str = "portrait",  # 'portrait'/'landscape'/'square'
    ) -> Optional[ClipResult]:
        ...
