"""Тесты для стоковых B-roll провайдеров (Pexels, Pixabay, Cascade)."""
from __future__ import annotations

import pytest

from app.services.broll_providers import get_provider
from app.services.broll_providers.base import ProviderError, ProviderUnavailable
from app.services.broll_providers.pexels import PexelsProvider
from app.services.broll_providers.pixabay import PixabayProvider
from app.services.broll_providers.cascade import CascadeProvider


# ── Factory ───────────────────────────────────────────────────────────────

def test_get_provider_unknown_raises():
    with pytest.raises(ProviderUnavailable):
        get_provider("unknown_xyz")


def test_get_provider_pexels():
    p = get_provider("pexels")
    assert p.name == "pexels"
    assert p.kind == "stock"


def test_get_provider_pixabay():
    p = get_provider("pixabay")
    assert p.name == "pixabay"
    assert p.kind == "stock"


def test_get_provider_cascade():
    p = get_provider("pexels_pixabay")
    assert isinstance(p, CascadeProvider)
    assert p.name == "pexels_pixabay"
    assert len(p.providers) == 2


# ── Pexels ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pexels_returns_clip_on_success():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    payload = {
        "videos": [{
            "id": 1, "duration": 6,
            "video_files": [
                {"file_type": "video/mp4", "link": "https://p1.mp4", "width": 1080, "height": 1920},
                {"file_type": "video/mp4", "link": "https://p1_4k.mp4", "width": 2160, "height": 3840},
            ],
        }],
    }
    with aioresponses() as m:
        m.get("https://api.pexels.com/videos/search?query=army+training&per_page=15&orientation=portrait&size=medium",
              payload=payload, status=200)
        clip = await PexelsProvider().search("army training", duration_sec=5, orientation="portrait")
        assert clip is not None
        assert clip["url"].startswith("https://p1")
        assert clip["source"] == "pexels"
        assert clip["cost_usd"] == 0.0
        assert clip["license"] == "Pexels"


@pytest.mark.asyncio
async def test_pexels_returns_none_on_no_results():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    with aioresponses() as m:
        m.get("https://api.pexels.com/videos/search?query=zzz&per_page=15&orientation=portrait&size=medium",
              payload={"videos": []}, status=200)
        clip = await PexelsProvider().search("zzz", duration_sec=5)
        assert clip is None


@pytest.mark.asyncio
async def test_pexels_unauthorized():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    with aioresponses() as m:
        m.get("https://api.pexels.com/videos/search?query=x&per_page=15&orientation=portrait&size=medium",
              payload={"error": "unauthorized"}, status=401)
        with pytest.raises(ProviderUnavailable):
            await PexelsProvider().search("x", duration_sec=5)


@pytest.mark.asyncio
async def test_pexels_no_api_key(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "pexels_api_key", "")
    with pytest.raises(ProviderUnavailable):
        await PexelsProvider().search("x", duration_sec=5)


# ── Pixabay ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pixabay_returns_clip_on_success():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    payload = {
        "hits": [{
            "duration": 8,
            "videos": {
                "large": {"url": "https://px.mp4", "width": 1920, "height": 1080},
                "medium": {"url": "https://px_m.mp4", "width": 1280, "height": 720},
            },
        }],
    }
    with aioresponses() as m:
        m.get("https://pixabay.com/api/videos/?key=test-pixabay&q=russian+nature&per_page=20&video_type=film&safesearch=true",
              payload=payload, status=200)
        # Запрос landscape — большое видео должно подойти
        clip = await PixabayProvider().search("russian nature", duration_sec=6, orientation="landscape")
        assert clip is not None
        assert clip["source"] == "pixabay"
        assert clip["cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_pixabay_no_results_returns_none():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    with aioresponses() as m:
        m.get("https://pixabay.com/api/videos/?key=test-pixabay&q=zzz&per_page=20&video_type=film&safesearch=true",
              payload={"hits": []}, status=200)
        clip = await PixabayProvider().search("zzz", duration_sec=5)
        assert clip is None


# ── Cascade ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cascade_returns_first_success():
    class _FailProvider:
        name = "fail"
        kind = "stock"
        async def search(self, q, *, duration_sec, orientation="portrait"):
            return None

    class _OkProvider:
        name = "ok"
        kind = "stock"
        async def search(self, q, *, duration_sec, orientation="portrait"):
            return {"url": "https://ok.mp4", "duration": 5, "source": "ok"}

    casc = CascadeProvider([_FailProvider(), _OkProvider()], name="test_casc")
    clip = await casc.search("any", duration_sec=5)
    assert clip and clip["source"] == "ok"


@pytest.mark.asyncio
async def test_cascade_skips_unavailable_provider():
    class _UnavailProvider:
        name = "unavail"
        kind = "stock"
        async def search(self, q, *, duration_sec, orientation="portrait"):
            raise ProviderUnavailable("no key")

    class _OkProvider:
        name = "ok"
        kind = "stock"
        async def search(self, q, *, duration_sec, orientation="portrait"):
            return {"url": "https://ok.mp4", "duration": 5, "source": "ok"}

    casc = CascadeProvider([_UnavailProvider(), _OkProvider()], name="test_casc")
    clip = await casc.search("any", duration_sec=5)
    assert clip and clip["source"] == "ok"


@pytest.mark.asyncio
async def test_cascade_returns_none_when_all_empty():
    class _Empty:
        name = "empty"
        kind = "stock"
        async def search(self, q, *, duration_sec, orientation="portrait"):
            return None
    casc = CascadeProvider([_Empty(), _Empty()], name="test_casc")
    assert await casc.search("any", duration_sec=5) is None
