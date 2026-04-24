"""PR2: Smoke-тесты ключевых эндпоинтов.

Проверяют, что ключевые HTTP-эндпоинты:
- успешно отвечают на корректных запросах,
- возвращают ожидаемую структуру JSON,
- возвращают 404 на несуществующих ресурсах.

НЕ вызывают реальные внешние API (Gemini/Claude/HeyGen/ElevenLabs/Deepgram).
"""

import os
import json
import pytest


# ────────────────────────────── helpers ────────────────────────────────────────

def _patch_cache_to_empty(monkeypatch):
    """Сбрасывает in-memory кэш HeyGen/ElevenLabs, чтобы get_*() вернул []."""
    from app.services import heygen_service, elevenlabs_service
    monkeypatch.setattr(heygen_service, "_avatars_cache", [])
    monkeypatch.setattr(heygen_service, "_private_avatars_cache", [])
    monkeypatch.setattr(elevenlabs_service, "_voices_cache", [])


# ────────────────────────────── HTML pages ────────────────────────────────────

def test_index_renders(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_text_renders(app_client):
    r = app_client.get("/text")
    assert r.status_code == 200


def test_audio_renders(app_client):
    r = app_client.get("/audio")
    assert r.status_code == 200


def test_video_renders(app_client):
    r = app_client.get("/video")
    assert r.status_code == 200


# ────────────────────────────── /api/config ───────────────────────────────────

def test_api_config_structure(app_client, monkeypatch):
    _patch_cache_to_empty(monkeypatch)
    r = app_client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    for key in ("models", "styles", "voices", "avatars", "private_avatars",
                "default_model"):
        assert key in data, f"missing key {key}"
    assert isinstance(data["models"], list)
    assert isinstance(data["styles"], list)


# ────────────────────────────── /api/history ──────────────────────────────────

@pytest.mark.parametrize("tab", ["text", "audio", "video"])
def test_api_history_empty(app_client, tab):
    r = app_client.get(f"/api/history?tab={tab}")
    assert r.status_code == 200
    data = r.json()
    assert "history" in data
    assert isinstance(data["history"], list)


# ────────────────────────────── /api/text/{slug} ──────────────────────────────

def test_api_text_404_on_unknown_slug(app_client):
    r = app_client.get("/api/text/nonexistent-000000")
    assert r.status_code == 404


# ────────────────────────────── /api/prompts ──────────────────────────────────

def test_api_prompts_structure(app_client):
    r = app_client.get("/api/prompts")
    assert r.status_code == 200
    data = r.json()
    assert "prompts" in data
    assert isinstance(data["prompts"], dict)


# ────────────────────────────── /api/cache/status ─────────────────────────────

def test_api_cache_status(app_client):
    r = app_client.get("/api/cache/status")
    assert r.status_code == 200
    data = r.json()
    for key in ("running", "last_updated_at", "error"):
        assert key in data


# ────────────────────────────── /api/tree/{slug} 404 ──────────────────────────

def test_api_tree_404_on_unknown_slug(app_client):
    r = app_client.get("/api/tree/nonexistent-000000")
    assert r.status_code == 404
