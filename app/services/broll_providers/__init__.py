"""
B-roll providers — единый интерфейс для поиска/генерации видео-клипов
для использования в Creatomate-монтаже.

Поддерживаются:
  - стоковые: pexels, pixabay (через get_provider("pexels_pixabay") — каскад)
  - AI: veo, runway, luma

Каждый провайдер реализует Protocol BrollProvider:
  async def search(query, *, duration_sec, orientation) -> Optional[ClipResult]
"""
from __future__ import annotations

from typing import Optional

from app.services.broll_providers.base import (
    BrollProvider,
    ClipResult,
    ProviderError,
    ProviderUnavailable,
)


def get_provider(name: str, model: str | None = None) -> BrollProvider:
    """Фабрика по строковому ключу из UI."""
    name = (name or "").lower()
    if name == "pexels":
        from app.services.broll_providers.pexels import PexelsProvider
        return PexelsProvider()
    if name == "pixabay":
        from app.services.broll_providers.pixabay import PixabayProvider
        return PixabayProvider()
    if name == "pexels_pixabay":
        from app.services.broll_providers.cascade import CascadeProvider
        from app.services.broll_providers.pexels import PexelsProvider
        from app.services.broll_providers.pixabay import PixabayProvider
        return CascadeProvider([PexelsProvider(), PixabayProvider()], name="pexels_pixabay")
    if name == "veo":
        from app.services.broll_providers.veo import VeoProvider
        return VeoProvider(model=model)
    if name == "runway":
        from app.services.broll_providers.runway import RunwayProvider
        return RunwayProvider(model=model)
    if name == "luma":
        from app.services.broll_providers.luma import LumaProvider
        return LumaProvider(model=model)
    raise ProviderUnavailable(f"Неизвестный B-roll провайдер: {name!r}")


__all__ = [
    "BrollProvider",
    "ClipResult",
    "ProviderError",
    "ProviderUnavailable",
    "get_provider",
]
