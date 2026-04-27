"""Тесты ветвления generate_montage_node по mode=auto/smart.

Покрывают:
1. Auto-режим (по умолчанию): payload Submagic не содержит items, но содержит
   magicBrolls. Backward compatibility — старые узлы без mode.
2. Smart-режим: при отсутствии таймкодов у родительского аудио вызывается
   deepgram.generate_timecodes ДО submagic.create_project и items[] передаются.
3. Smart-режим: items[] правильно прокидываются в Submagic, magicBrolls
   принудительно False.
4. submagic_service.create_project: items + magic_brolls=True → magicBrolls=False.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest


# ─────────────────────── unit-тест submagic_service ──────────────────────────


@pytest.mark.asyncio
async def test_create_project_with_items_forces_magic_brolls_false(monkeypatch):
    """items + magic_brolls=True => в payload magicBrolls=False (без смешения)."""
    from app.services import submagic_service

    captured = {}

    class _FakeResp:
        status = 201
        async def json(self): return {"id": "p1", "status": "queued"}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["payload"] = json
            return _FakeResp()

    monkeypatch.setattr(submagic_service.aiohttp, "ClientSession", lambda: _FakeSession())

    items = [{"type": "ai-broll", "startTime": 1.5, "endTime": 5.0,
              "prompt": "russian office", "layout": "cover"}]

    result = await submagic_service.create_project(
        video_url="https://x.test/v.mp4",
        magic_brolls=True,
        items=items,
    )

    assert result["id"] == "p1"
    payload = captured["payload"]
    assert payload["magicBrolls"] is False
    assert payload["items"] == items


@pytest.mark.asyncio
async def test_create_project_without_items_keeps_magic_brolls(monkeypatch):
    """Auto-режим: items не передан — magicBrolls остаётся как был."""
    from app.services import submagic_service

    captured = {}

    class _FakeResp:
        status = 201
        async def json(self): return {"id": "p2", "status": "queued"}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        def post(self, url, headers=None, json=None):
            captured["payload"] = json
            return _FakeResp()

    monkeypatch.setattr(submagic_service.aiohttp, "ClientSession", lambda: _FakeSession())

    await submagic_service.create_project(
        video_url="https://x.test/v.mp4",
        magic_brolls=True,
    )
    payload = captured["payload"]
    assert payload["magicBrolls"] is True
    assert "items" not in payload


# ─────────────────────────── интеграционные ветви ────────────────────────────


def _video_node(parent_audio_id="audio-1"):
    return {
        "node_id": "video-1",
        "node_type": "video",
        "parent_node_id": parent_audio_id,
        "content_url": "https://armeykabrain.net/static/video/v.mp4",
        "stats_json": {"audio_duration_sec": 30},
        "params_json": {},
    }


def _audio_node_with_tc(tc_url="/static/audio/tc_test.json"):
    return {
        "node_id": "audio-1",
        "node_type": "audio",
        "content_url": "/static/audio/a.mp3",
        "content_url_original": "/static/audio/a.mp3",
        "stats_json": {"timecodes_json_url": tc_url, "duration_sec": 30},
    }


def _audio_node_no_tc():
    return {
        "node_id": "audio-1",
        "node_type": "audio",
        "content_url": "/static/audio/a.mp3",
        "content_url_original": "/static/audio/a.mp3",
        "stats_json": {"duration_sec": 30},
    }


def _completed_submagic_status():
    return {
        "id": "p1", "status": "completed",
        "downloadUrl": "https://files.submagic.co/r.mp4",
        "previewUrl":  "https://app.submagic.co/preview/p1",
        "videoMetaData": {"duration": 28.5, "width": 1080, "height": 1920, "fps": 30},
    }


@pytest.mark.asyncio
async def test_auto_mode_does_not_call_planner_or_deepgram(monkeypatch):
    from app.services import tree_service, submagic_service

    monkeypatch.setattr(tree_service, "get_tree_node", lambda nid: _video_node())
    monkeypatch.setattr(tree_service, "save_tree_node", lambda n: n)
    monkeypatch.setattr(tree_service, "_count_nodes_of_type", lambda *a, **k: 0)
    monkeypatch.setattr(tree_service, "update_tree_node_status", lambda *a, **k: None)
    monkeypatch.setattr(tree_service, "update_tree_node_stats", lambda *a, **k: None)

    create_mock = AsyncMock(return_value={"id": "p1", "status": "queued"})
    get_mock = AsyncMock(return_value=_completed_submagic_status())
    deepgram_mock = AsyncMock()
    planner_mock = AsyncMock()

    monkeypatch.setattr(submagic_service, "create_project", create_mock)
    monkeypatch.setattr(submagic_service, "get_project", get_mock)
    monkeypatch.setattr(tree_service, "deepgram_generate_timecodes", deepgram_mock)
    monkeypatch.setattr(tree_service, "plan_broll_items", planner_mock)
    monkeypatch.setattr(tree_service.asyncio, "sleep", AsyncMock())

    queue: asyncio.Queue = asyncio.Queue()
    await tree_service.generate_montage_node(
        queue, "260424-00001", "video-1",
        {"mode": "auto", "magic_brolls": True, "magic_brolls_pct": 50},
    )

    create_mock.assert_awaited_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs.get("items") is None
    assert kwargs.get("magic_brolls") is True
    deepgram_mock.assert_not_called()
    planner_mock.assert_not_called()


@pytest.mark.asyncio
async def test_smart_mode_uses_existing_timecodes_and_passes_items(monkeypatch):
    from app.services import tree_service, submagic_service

    tc_url = "/static/audio/tc_test.json"
    parent_video = _video_node()
    parent_audio = _audio_node_with_tc(tc_url=tc_url)
    monkeypatch.setattr(tree_service, "_load_deepgram_json",
                        lambda url: {"results": {"channels": [{"alternatives": [{}]}]}})

    def _get(nid):
        if nid == "video-1": return parent_video
        if nid == "audio-1": return parent_audio
        return None

    monkeypatch.setattr(tree_service, "get_tree_node", _get)
    monkeypatch.setattr(tree_service, "save_tree_node", lambda n: n)
    monkeypatch.setattr(tree_service, "_count_nodes_of_type", lambda *a, **k: 0)
    monkeypatch.setattr(tree_service, "update_tree_node_status", lambda *a, **k: None)
    monkeypatch.setattr(tree_service, "update_tree_node_stats", lambda *a, **k: None)

    fake_items = [
        {"type": "ai-broll", "startTime": 2.0, "endTime": 8.0,
         "prompt": "p1", "layout": "cover"},
    ]
    fake_planner_stats = {"broll_items_count": 1, "video_duration_sec": 30,
                          "llm_model": "gemini-flash-latest", "in_tokens": 10,
                          "out_tokens": 5, "cost": 0.0001}
    planner_mock = AsyncMock(return_value=(fake_items, fake_planner_stats))
    deepgram_mock = AsyncMock()  # не должно вызываться
    create_mock = AsyncMock(return_value={"id": "p1", "status": "queued"})
    get_mock = AsyncMock(return_value=_completed_submagic_status())

    monkeypatch.setattr(tree_service, "plan_broll_items", planner_mock)
    monkeypatch.setattr(tree_service, "deepgram_generate_timecodes", deepgram_mock)
    monkeypatch.setattr(submagic_service, "create_project", create_mock)
    monkeypatch.setattr(submagic_service, "get_project", get_mock)
    monkeypatch.setattr(tree_service.asyncio, "sleep", AsyncMock())

    queue: asyncio.Queue = asyncio.Queue()
    await tree_service.generate_montage_node(
        queue, "260424-00001", "video-1",
        {"mode": "smart", "density": "medium", "topic_hint": "law", "russia_only": True},
    )

    deepgram_mock.assert_not_called()
    planner_mock.assert_awaited_once()
    create_mock.assert_awaited_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs.get("items") == fake_items
    assert kwargs.get("magic_brolls") is False


@pytest.mark.asyncio
async def test_smart_mode_auto_generates_missing_timecodes(monkeypatch):
    """Если у родительского аудио нет timecodes_json_url — Deepgram запускается до Submagic."""
    from app.services import tree_service, submagic_service

    tc_url = "/static/audio/tc_auto.json"
    parent_video = _video_node()
    parent_audio = _audio_node_no_tc()
    monkeypatch.setattr(tree_service, "_load_deepgram_json",
                        lambda url: {"results": {"channels": [{"alternatives": [{}]}]}})

    def _get(nid):
        if nid == "video-1": return parent_video
        if nid == "audio-1": return parent_audio
        return None

    call_order: list[str] = []

    monkeypatch.setattr(tree_service, "get_tree_node", _get)
    monkeypatch.setattr(tree_service, "save_tree_node", lambda n: n)
    monkeypatch.setattr(tree_service, "_count_nodes_of_type", lambda *a, **k: 0)
    monkeypatch.setattr(tree_service, "update_tree_node_status", lambda *a, **k: None)
    monkeypatch.setattr(tree_service, "update_tree_node_stats", lambda *a, **k: None)

    async def _deepgram(audio_url):
        call_order.append("deepgram")
        return {"json_url": tc_url, "vtt_url": "/x.vtt", "cost": 0.001, "duration_sec": 30}

    async def _planner(*a, **kw):
        call_order.append("planner")
        return [{"type": "ai-broll", "startTime": 2.0, "endTime": 8.0,
                 "prompt": "p", "layout": "cover"}], {
            "broll_items_count": 1, "video_duration_sec": 30,
            "llm_model": "gemini-flash-latest", "in_tokens": 0, "out_tokens": 0, "cost": 0.0,
        }

    async def _submagic_create(**kw):
        call_order.append("submagic_create")
        return {"id": "p1", "status": "queued"}

    monkeypatch.setattr(tree_service, "deepgram_generate_timecodes", _deepgram)
    monkeypatch.setattr(tree_service, "plan_broll_items", _planner)
    monkeypatch.setattr(submagic_service, "create_project", _submagic_create)
    monkeypatch.setattr(submagic_service, "get_project", AsyncMock(return_value=_completed_submagic_status()))
    monkeypatch.setattr(tree_service.asyncio, "sleep", AsyncMock())

    queue: asyncio.Queue = asyncio.Queue()
    await tree_service.generate_montage_node(
        queue, "slug-test", "video-1",
        {"mode": "smart", "density": "medium", "topic_hint": "auto"},
    )

    # Порядок: сначала deepgram, потом planner, потом submagic
    assert call_order == ["deepgram", "planner", "submagic_create"]


@pytest.mark.asyncio
async def test_default_mode_when_missing_is_auto(monkeypatch):
    """Backward compatibility: params без 'mode' трактуются как auto."""
    from app.services import tree_service, submagic_service

    monkeypatch.setattr(tree_service, "get_tree_node", lambda nid: _video_node())
    monkeypatch.setattr(tree_service, "save_tree_node", lambda n: n)
    monkeypatch.setattr(tree_service, "_count_nodes_of_type", lambda *a, **k: 0)
    monkeypatch.setattr(tree_service, "update_tree_node_status", lambda *a, **k: None)
    monkeypatch.setattr(tree_service, "update_tree_node_stats", lambda *a, **k: None)

    create_mock = AsyncMock(return_value={"id": "p1", "status": "queued"})
    monkeypatch.setattr(submagic_service, "create_project", create_mock)
    monkeypatch.setattr(submagic_service, "get_project", AsyncMock(return_value=_completed_submagic_status()))
    monkeypatch.setattr(tree_service, "deepgram_generate_timecodes", AsyncMock())
    monkeypatch.setattr(tree_service, "plan_broll_items", AsyncMock())
    monkeypatch.setattr(tree_service.asyncio, "sleep", AsyncMock())

    queue: asyncio.Queue = asyncio.Queue()
    await tree_service.generate_montage_node(
        queue, "slug", "video-1",
        {"magic_brolls": True},  # ни mode, ни smart-полей
    )

    create_mock.assert_awaited_once()
    assert create_mock.call_args.kwargs.get("items") is None
