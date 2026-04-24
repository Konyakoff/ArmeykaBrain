"""Общие фикстуры для всех тестов.

Цели:
1. Изолировать SQLite БД (tmp_path) от продовой db/dialogs.db.
2. Гарантировать, что переменные окружения для внешних API не пустые
   (Settings из config.py выбросит ValidationError, если их нет).
3. Замокать сетевые HTTP-вызовы через respx, чтобы тесты были hermetic.
"""

from __future__ import annotations

import os
import sys
import pathlib
import pytest


# ───────────────────────────── env (до импортов app.*) ─────────────────────────
# Settings парсится в момент импорта app.core.config, поэтому ENV нужно поднять
# раньше, чем какой-либо тест дернёт что-то из app.
os.environ.setdefault("GEMINI_API_KEY", "test-gemini")
os.environ.setdefault("ELEVENLABS_API_KEY", "test-eleven")
os.environ.setdefault("HEYGEN_API_KEY", "test-heygen")
os.environ.setdefault("DEEPGRAM_API_KEY", "test-deepgram")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-claude")

# Корень проекта в sys.path (на случай запуска не из корня)
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────── db isolation ─────────────────────────────────

@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Подменяет engine/DB_PATH на tmp_path и инициализирует схему.

    Используйте эту фикстуру в тестах, которым нужна реальная БД.
    """
    from sqlmodel import create_engine
    from app.db import database as db

    db_file = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{db_file}", echo=False)
    monkeypatch.setattr(db, "engine", test_engine)
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    monkeypatch.setattr(db, "DB_DIR", str(tmp_path))
    db.init_db()
    return test_engine


# ─────────────────────────── HTTP mocks (respx) ───────────────────────────────

@pytest.fixture
def mock_external_apis(respx_mock):
    """Заглушки для всех внешних API. Тесты НЕ должны ходить в реальную сеть."""
    import re

    respx_mock.route(host="generativelanguage.googleapis.com").respond(
        200, json={"candidates": []}
    )
    respx_mock.route(host="api.anthropic.com").respond(
        200, json={"content": [{"text": ""}], "usage": {"input_tokens": 0, "output_tokens": 0}}
    )
    respx_mock.route(host="api.elevenlabs.io").respond(200, json={"voices": []})
    respx_mock.route(host="api.heygen.com").respond(200, json={"data": {"avatars": []}})
    respx_mock.route(host="api.deepgram.com").respond(200, json={"results": {}})
    return respx_mock


# ─────────────────────────────── FastAPI client ────────────────────────────────

@pytest.fixture
def app_client(monkeypatch, tmp_path):
    """TestClient для FastAPI с изолированной БД и без startup-ивентов.

    Внешние API НЕ замоканы здесь — добавьте mock_external_apis в тест,
    если эндпоинт делает сетевые вызовы.
    """
    from fastapi.testclient import TestClient
    from sqlmodel import create_engine
    from app.db import database as db

    # Подменяем engine ДО импорта app.main, чтобы init_db() в startup
    # шёл по нашему тестовому файлу.
    db_file = tmp_path / "test_client.db"
    test_engine = create_engine(f"sqlite:///{db_file}", echo=False)
    monkeypatch.setattr(db, "engine", test_engine)
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    monkeypatch.setattr(db, "DB_DIR", str(tmp_path))

    from app.main import app
    with TestClient(app) as client:
        yield client
