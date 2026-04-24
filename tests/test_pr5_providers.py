"""Тесты PR5: LLMProvider Protocol + ClaudeProvider/GeminiProvider.

Проверяем:
1. Фабрика get_provider возвращает правильный класс по имени модели.
2. Оба провайдера соответствуют LLMProvider-протоколу (методы и сигнатуры).
3. calculate_cost для известных моделей даёт > 0.
4. Каждый async-метод работает поверх замоканного делегата (top_ids,
   expert_analysis, audio_script возвращают корректные Step*Result).
5. В app.services.core/tree_service нет более конструкции _is_claude(...).
"""

from __future__ import annotations

import asyncio
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from app.models.schemas import Step1Result, Step2Result, Step3Result
from app.services.llm import (
    ClaudeProvider,
    GeminiProvider,
    LLMProvider,
    get_provider,
)


# ─── фабрика и протокол ──────────────────────────────────────────────────────


def test_factory_returns_claude_for_claude_models():
    p = get_provider("claude-opus-4-7")
    assert isinstance(p, ClaudeProvider)
    assert p.name == "claude"


def test_factory_returns_gemini_for_gemini_models():
    for m in ("gemini-3.1-pro-preview", "gemini-flash-latest", "gpt-4o", ""):
        p = get_provider(m)
        assert isinstance(p, GeminiProvider), f"failed for model={m!r}"
        assert p.name == "gemini"


def test_providers_satisfy_protocol():
    # runtime_checkable Protocol проверяет наличие атрибутов и методов
    assert isinstance(GeminiProvider(), LLMProvider)
    assert isinstance(ClaudeProvider(), LLMProvider)


# ─── calculate_cost ──────────────────────────────────────────────────────────


def test_calculate_cost_gemini_known_model_positive():
    p = GeminiProvider()
    in_cost, out_cost = p.calculate_cost(1_000_000, 1_000_000, "gemini-3.1-pro-preview")
    assert in_cost > 0
    assert out_cost > 0


def test_calculate_cost_claude_known_model_positive():
    p = ClaudeProvider()
    # claude-opus-4-7 присутствует в data/ai_models.json
    in_cost, out_cost = p.calculate_cost(1_000_000, 1_000_000, "claude-opus-4-7")
    assert in_cost > 0
    assert out_cost > 0


def test_calculate_cost_unknown_model_returns_zeros():
    assert GeminiProvider().calculate_cost(100, 100, "unknown-model") == (0.0, 0.0)
    assert ClaudeProvider().calculate_cost(100, 100, "unknown-model") == (0.0, 0.0)


# ─── async-делегирование (моками) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gemini_top_ids_delegates(monkeypatch):
    expected = Step1Result(articles=[], query_category="legal", in_tokens=10, out_tokens=20)
    fake = AsyncMock(return_value=expected)
    monkeypatch.setattr("app.services.gemini_service.get_top_ids", fake)
    p = GeminiProvider()
    res = await p.top_ids("вопрос", "gemini-3.1-pro-preview")
    fake.assert_awaited_once_with("вопрос", "gemini-3.1-pro-preview")
    assert res is expected


@pytest.mark.asyncio
async def test_claude_top_ids_delegates(monkeypatch):
    expected = Step1Result(articles=[], query_category="legal", in_tokens=5, out_tokens=7)
    fake = AsyncMock(return_value=expected)
    monkeypatch.setattr("app.services.claude_service.get_top_ids_claude", fake)
    p = ClaudeProvider()
    res = await p.top_ids("вопрос", "claude-opus-4-7")
    fake.assert_awaited_once_with("вопрос", "claude-opus-4-7")
    assert res is expected


@pytest.mark.asyncio
async def test_gemini_expert_analysis_delegates(monkeypatch):
    expected = Step2Result(answer="ok", in_tokens=11, out_tokens=22)
    fake = AsyncMock(return_value=expected)
    monkeypatch.setattr("app.services.gemini_service.get_expert_analysis", fake)
    p = GeminiProvider()
    res = await p.expert_analysis(
        "q", "ctx", style="telegram_yur", max_length=2000,
        override_style="custom", model="gemini-3.1-pro-preview",
    )
    fake.assert_awaited_once_with(
        "q", "ctx", style="telegram_yur", max_length=2000, override_style="custom",
    )
    assert res is expected


@pytest.mark.asyncio
async def test_claude_expert_analysis_delegates(monkeypatch):
    expected = Step2Result(answer="ok", in_tokens=3, out_tokens=4)
    fake = AsyncMock(return_value=expected)
    monkeypatch.setattr("app.services.claude_service.get_expert_analysis_claude", fake)
    p = ClaudeProvider()
    res = await p.expert_analysis(
        "q", "ctx", style="telegram_yur", max_length=2000,
        override_style=None, model="claude-sonnet-4-6",
    )
    fake.assert_awaited_once_with(
        "q", "ctx", style="telegram_yur", max_length=2000,
        override_style=None, model_name="claude-sonnet-4-6",
    )
    assert res is expected


@pytest.mark.asyncio
async def test_gemini_audio_script_delegates(monkeypatch):
    expected = Step3Result(script="hello", in_tokens=1, out_tokens=2)
    fake = AsyncMock(return_value=expected)
    monkeypatch.setattr("app.services.gemini_service.generate_audio_script", fake)
    p = GeminiProvider()
    res = await p.audio_script("expert", duration=60, wpm=150, override="o", model="gemini-flash-latest")
    fake.assert_awaited_once_with("expert", duration=60, wpm=150, override="o")
    assert res is expected


@pytest.mark.asyncio
async def test_claude_audio_script_delegates(monkeypatch):
    expected = Step3Result(script="hello", in_tokens=1, out_tokens=2)
    fake = AsyncMock(return_value=expected)
    monkeypatch.setattr("app.services.claude_service.generate_audio_script_claude", fake)
    p = ClaudeProvider()
    res = await p.audio_script("expert", duration=60, wpm=150, override=None, model="claude-haiku-4-5")
    fake.assert_awaited_once_with(
        "expert", duration=60, wpm=150, override=None, model_name="claude-haiku-4-5",
    )
    assert res is expected


# ─── гарантия отсутствия старых ветвлений ───────────────────────────────────


def test_no_is_claude_branches_in_orchestrators():
    """В core.py/tree_service.py не должно остаться вызовов _is_claude(...)."""
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("app/services/core.py", "app/services/tree_service.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "_is_claude(" not in text, f"{name}: остались вызовы _is_claude(...)"
        assert "def _is_claude" not in text, f"{name}: остался хелпер _is_claude"
