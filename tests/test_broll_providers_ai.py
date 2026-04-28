"""Тесты для AI B-roll провайдеров (Veo, Runway, Luma)."""
from __future__ import annotations

import pytest

from app.services.broll_providers.base import ProviderError, ProviderUnavailable
from app.services.broll_providers.veo import VeoProvider
from app.services.broll_providers.runway import RunwayProvider
from app.services.broll_providers.luma import LumaProvider


# ── Veo ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_veo_no_api_key(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "gemini_api_key", "")
    with pytest.raises(ProviderUnavailable):
        await VeoProvider().search("anything", duration_sec=5)


@pytest.mark.asyncio
async def test_veo_full_flow_direct_url(monkeypatch):
    """Если Veo вернул прямой HTTPS URL — возвращаем его как есть, без скачивания."""
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    import re as _re

    async def _no_sleep(_):
        return None
    import app.services.broll_providers.veo as veo_mod
    monkeypatch.setattr(veo_mod.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        # Первая попытка — veo-3.1-generate-001 (основная модель)
        m.post(
            _re.compile(r"https://generativelanguage\.googleapis\.com/v1beta/models/veo-3\.1-generate-001:predictLongRunning.*"),
            payload={"name": "operations/op_123"},
            status=200,
        )
        m.get(
            _re.compile(r"https://generativelanguage\.googleapis\.com/v1beta/operations/op_123.*"),
            payload={
                "done": True,
                "response": {
                    "generatedVideos": [
                        {"video": {"uri": "https://veo.example/clip.mp4"}}
                    ],
                },
            },
            status=200,
        )

        clip = await VeoProvider(poll_interval=0, max_wait_sec=2).search(
            "russian soldiers training", duration_sec=8, orientation="portrait"
        )

    assert clip is not None
    # Прямой URL — возвращается без изменений (не generativelanguage.googleapis.com)
    assert clip["url"] == "https://veo.example/clip.mp4"
    assert clip["source"] == "veo"
    assert clip["cost_usd"] == 0.50


@pytest.mark.asyncio
async def test_veo_model_fallback(monkeypatch):
    """Если veo-3.1 вернул 404, должны попробовать veo-3.0."""
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    import re as _re

    async def _no_sleep(_):
        return None
    import app.services.broll_providers.veo as veo_mod
    monkeypatch.setattr(veo_mod.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        # veo-3.1 → 404
        m.post(
            _re.compile(r".*veo-3\.1-generate-001:predictLongRunning.*"),
            payload={"error": {"message": "model not found"}},
            status=404,
        )
        # veo-3.0 → успех
        m.post(
            _re.compile(r".*veo-3\.0-generate-001:predictLongRunning.*"),
            payload={"name": "operations/op_fallback"},
            status=200,
        )
        m.get(
            _re.compile(r".*operations/op_fallback.*"),
            payload={
                "done": True,
                "response": {
                    "generatedVideos": [{"video": {"uri": "https://fallback.example/v.mp4"}}]
                },
            },
            status=200,
        )

        clip = await VeoProvider(poll_interval=0, max_wait_sec=2).search(
            "test fallback", duration_sec=8
        )

    assert clip is not None
    assert clip["url"] == "https://fallback.example/v.mp4"


@pytest.mark.asyncio
async def test_veo_gemini_files_download(monkeypatch, tmp_path):
    """Если URI — Gemini Files API, скачиваем и сохраняем локально."""
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    import re as _re
    import app.services.broll_providers.veo as veo_mod

    # Перенаправляем статическую папку в tmp
    monkeypatch.setattr(veo_mod, "BROLL_STATIC_DIR", tmp_path)
    monkeypatch.setattr(veo_mod, "HOST_URL", "https://test.example")

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(veo_mod.asyncio, "sleep", _no_sleep)

    gemini_uri = "https://generativelanguage.googleapis.com/v1beta/files/abc123xyz"

    with aioresponses() as m:
        m.post(
            _re.compile(r".*veo-3\.1-generate-001:predictLongRunning.*"),
            payload={"name": "operations/op_dl"},
            status=200,
        )
        m.get(
            _re.compile(r".*operations/op_dl.*"),
            payload={
                "done": True,
                "response": {"generatedVideos": [{"video": {"uri": gemini_uri}}]},
            },
            status=200,
        )
        # Мок скачивания файла
        m.get(
            _re.compile(r".*generativelanguage\.googleapis\.com/v1beta/files/abc123xyz.*"),
            body=b"FAKEVIDEO",
            headers={"content-type": "video/mp4"},
            status=200,
        )

        clip = await VeoProvider(poll_interval=0, max_wait_sec=2).search(
            "test download", duration_sec=8
        )

    assert clip is not None
    assert clip["url"].startswith("https://test.example/static/broll/")
    assert clip["url"].endswith(".mp4")
    # Файл сохранился на диск
    saved = list(tmp_path.glob("*.mp4"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"FAKEVIDEO"


@pytest.mark.asyncio
async def test_veo_gs_uri_raises(monkeypatch):
    """gs:// URI должен бросить ProviderError с понятным сообщением."""
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    import re as _re
    import app.services.broll_providers.veo as veo_mod

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(veo_mod.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        m.post(
            _re.compile(r".*veo-3\.1-generate-001:predictLongRunning.*"),
            payload={"name": "operations/op_gs"},
            status=200,
        )
        m.get(
            _re.compile(r".*operations/op_gs.*"),
            payload={
                "done": True,
                "response": {
                    "generatedVideos": [{"video": {"uri": "gs://bucket/video.mp4"}}]
                },
            },
            status=200,
        )

        with pytest.raises(ProviderError, match="gs://"):
            await VeoProvider(poll_interval=0, max_wait_sec=2).search("x", duration_sec=8)


@pytest.mark.asyncio
async def test_veo_failed_op(monkeypatch):
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    import re as _re

    async def _no_sleep(_):
        return None
    import app.services.broll_providers.veo as veo_mod
    monkeypatch.setattr(veo_mod.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        m.post(
            _re.compile(r".*veo-3\.1-generate-001:predictLongRunning.*"),
            payload={"name": "operations/op_x"},
            status=200,
        )
        m.get(
            _re.compile(r".*operations/op_x.*"),
            payload={"done": True, "error": {"message": "policy violation"}},
            status=200,
        )

        with pytest.raises(ProviderError, match="policy violation"):
            await VeoProvider(poll_interval=0, max_wait_sec=2).search("x", duration_sec=8)


# ── Runway ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_runway_no_api_key(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "runway_api_key", "")
    with pytest.raises(ProviderUnavailable):
        await RunwayProvider().search("x", duration_sec=5)


@pytest.mark.asyncio
async def test_runway_full_flow(monkeypatch):
    aioresponses = pytest.importorskip("aioresponses").aioresponses

    async def _no_sleep(_):
        return None
    import app.services.broll_providers.runway as r_mod
    monkeypatch.setattr(r_mod.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        m.post(
            "https://api.dev.runwayml.com/v1/text_to_video",
            payload={"id": "task_111"},
            status=200,
        )
        m.get(
            "https://api.dev.runwayml.com/v1/tasks/task_111",
            payload={"status": "SUCCEEDED", "output": ["https://run.example/x.mp4"]},
            status=200,
        )

        clip = await RunwayProvider(poll_interval=0, max_wait_sec=2).search(
            "documents close-up", duration_sec=5, orientation="portrait"
        )
    assert clip and clip["url"] == "https://run.example/x.mp4"
    assert clip["source"] == "runway"
    assert clip["cost_usd"] == 0.25  # 5 * $0.05


@pytest.mark.asyncio
async def test_runway_failed_task(monkeypatch):
    aioresponses = pytest.importorskip("aioresponses").aioresponses

    async def _no_sleep(_):
        return None
    import app.services.broll_providers.runway as r_mod
    monkeypatch.setattr(r_mod.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        m.post("https://api.dev.runwayml.com/v1/text_to_video",
               payload={"id": "task_f"}, status=200)
        m.get("https://api.dev.runwayml.com/v1/tasks/task_f",
              payload={"status": "FAILED", "failure": "moderation"}, status=200)

        with pytest.raises(ProviderError, match="FAILED"):
            await RunwayProvider(poll_interval=0, max_wait_sec=2).search("x", duration_sec=5)


# ── Luma ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_luma_no_api_key(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "luma_api_key", "")
    with pytest.raises(ProviderUnavailable):
        await LumaProvider().search("x", duration_sec=5)


@pytest.mark.asyncio
async def test_luma_full_flow(monkeypatch):
    aioresponses = pytest.importorskip("aioresponses").aioresponses

    async def _no_sleep(_):
        return None
    import app.services.broll_providers.luma as l_mod
    monkeypatch.setattr(l_mod.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        m.post(
            "https://api.lumalabs.ai/dream-machine/v1/generations",
            payload={"id": "gen_1"},
            status=201,
        )
        m.get(
            "https://api.lumalabs.ai/dream-machine/v1/generations/gen_1",
            payload={"state": "completed", "assets": {"video": "https://luma.example/v.mp4"}},
            status=200,
        )

        clip = await LumaProvider(poll_interval=0, max_wait_sec=2).search(
            "russian forest scenery", duration_sec=5, orientation="portrait"
        )
    assert clip and clip["url"] == "https://luma.example/v.mp4"
    assert clip["source"] == "luma"
    assert clip["cost_usd"] == 0.20
