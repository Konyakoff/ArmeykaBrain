"""Тесты для creatomate_service: расчёт кредитов и REST-вызовы (mocked)."""
from __future__ import annotations

import pytest

from app.services import creatomate_service


# ── credits ────────────────────────────────────────────────────────────────

def test_calculate_credits_small_video():
    # 1080x1920x30x10 = 622,080,000 → 6.22 → 7 credits
    credits = creatomate_service.calculate_credits(1080, 1920, 30, 10)
    assert credits == 7


def test_calculate_credits_minimum_one():
    credits = creatomate_service.calculate_credits(100, 100, 24, 0.1)
    assert credits == 1


def test_calculate_credits_zero_duration_returns_one():
    assert creatomate_service.calculate_credits(1080, 1920, 30, 0) == 1


def test_calculate_credits_60s_1080p_30fps():
    # 1080*1920*30*60 / 1e8 = 37.32 → ceil = 38 credits ≈ $0.156
    credits = creatomate_service.calculate_credits(1080, 1920, 30, 60)
    assert credits == 38


def test_calculate_cost_usd_proportional():
    cost = creatomate_service.calculate_cost_usd(100)
    assert cost == round(100 * creatomate_service.USD_PER_CREDIT, 4)


# ── HTTP (mocked via respx) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_render_returns_first_item(respx_mock):
    import httpx
    # Creatomate возвращает массив рендеров
    respx_mock.post("https://api.creatomate.com/v2/renders").mock(
        return_value=httpx.Response(200, json=[
            {"id": "ren_1", "status": "queued"},
        ])
    )
    # creatomate_service использует aiohttp, не httpx — заменим временно через monkeypatch
    # либо проверим напрямую вызов через aiohttp_client мок

    # Альтернатива: используем aiohttp test mock через aioresponses
    pass  # skip — заменяется тестом ниже через aioresponses


@pytest.mark.asyncio
async def test_create_render_via_aioresponses():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    with aioresponses() as m:
        m.post(
            "https://api.creatomate.com/v2/renders",
            payload=[{"id": "ren_1", "status": "queued"}],
            status=200,
        )
        result = await creatomate_service.create_render(
            {"output_format": "mp4", "width": 1080, "height": 1920, "elements": []}
        )
        assert result["id"] == "ren_1"
        assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_create_render_handles_dict_response():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    with aioresponses() as m:
        m.post(
            "https://api.creatomate.com/v2/renders",
            payload={"id": "ren_dict", "status": "queued"},
            status=200,
        )
        result = await creatomate_service.create_render(
            {"output_format": "mp4", "width": 1080, "height": 1920, "elements": []}
        )
        assert result["id"] == "ren_dict"


@pytest.mark.asyncio
async def test_create_render_raises_on_error():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    with aioresponses() as m:
        m.post(
            "https://api.creatomate.com/v2/renders",
            payload={"message": "Invalid render script"},
            status=400,
        )
        with pytest.raises(Exception, match="Invalid render script"):
            await creatomate_service.create_render({"foo": "bar"})


@pytest.mark.asyncio
async def test_get_render_returns_status():
    aioresponses = pytest.importorskip("aioresponses").aioresponses
    with aioresponses() as m:
        m.get(
            "https://api.creatomate.com/v1/renders/ren_xyz",
            payload={"id": "ren_xyz", "status": "succeeded", "url": "https://cdn/result.mp4"},
            status=200,
        )
        result = await creatomate_service.get_render("ren_xyz")
        assert result["status"] == "succeeded"
        assert result["url"] == "https://cdn/result.mp4"


@pytest.mark.asyncio
async def test_wait_for_render_succeeds_quickly(monkeypatch):
    aioresponses = pytest.importorskip("aioresponses").aioresponses

    # Make sleep instant
    async def _no_sleep(_):
        return None

    monkeypatch.setattr(creatomate_service.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        m.get(
            "https://api.creatomate.com/v1/renders/ren_w",
            payload={"id": "ren_w", "status": "succeeded", "url": "https://x.mp4"},
            status=200,
        )
        result = await creatomate_service.wait_for_render("ren_w", interval_sec=0, max_attempts=3)
        assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_wait_for_render_raises_on_failed(monkeypatch):
    aioresponses = pytest.importorskip("aioresponses").aioresponses

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(creatomate_service.asyncio, "sleep", _no_sleep)

    with aioresponses() as m:
        m.get(
            "https://api.creatomate.com/v1/renders/ren_f",
            payload={"id": "ren_f", "status": "failed", "error_message": "boom"},
            status=200,
        )
        with pytest.raises(Exception, match="boom"):
            await creatomate_service.wait_for_render("ren_f", interval_sec=0, max_attempts=3)
