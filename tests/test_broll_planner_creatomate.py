"""Тесты для plan_broll_for_creatomate (LLM мокается)."""
from __future__ import annotations

import pytest

from app.services import broll_planner


def _make_dg(total_sec: float = 60.0, n_sentences: int = 8):
    """Создаёт минимальный Deepgram-JSON со sentence-сегментами."""
    step = total_sec / n_sentences
    sentences = []
    for i in range(n_sentences):
        sentences.append({
            "text": f"Это предложение номер {i+1} с осмысленным текстом для броля.",
            "start": i * step,
            "end": (i + 1) * step,
        })
    return {
        "results": {
            "channels": [{
                "alternatives": [{
                    "paragraphs": {"paragraphs": [{"sentences": sentences}]},
                }],
            }],
        },
    }


@pytest.mark.asyncio
async def test_plan_returns_structure(monkeypatch):
    async def _fake_llm(model, system, user):
        # Возвращаем по 1 запросу на каждый сегмент
        rows = {0: {"query_ru": "армия рф", "query_en": "russian army training", "prompt": "Cinematic..."},
                1: {"query_ru": "офис юр", "query_en": "legal office", "prompt": "Cinematic..."},
                2: {"query_ru": "документы", "query_en": "documents desk", "prompt": "Cinematic..."},
                3: {"query_ru": "врач", "query_en": "doctor stethoscope", "prompt": "Cinematic..."}}
        return rows, 100, 50

    monkeypatch.setattr(broll_planner, "_call_gemini_json_rows", _fake_llm)
    monkeypatch.setattr(broll_planner, "_gemini_cost", lambda *a, **kw: 0.0001)

    plan, stats = await broll_planner.plan_broll_for_creatomate(
        _make_dg(60.0, n_sentences=8),
        density="medium",
        clip_duration=5,
        topic_hint="army",
    )
    assert isinstance(plan, list)
    assert len(plan) >= 1
    for item in plan:
        assert "start" in item and "end" in item and "duration" in item
        assert "query_ru" in item and "query_en" in item and "prompt" in item
    assert stats["llm_model"]
    assert stats["planned_count"] == len(plan)


@pytest.mark.asyncio
async def test_plan_falls_back_on_llm_error(monkeypatch):
    async def _bad_llm(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(broll_planner, "_call_gemini_json_rows", _bad_llm)

    plan, stats = await broll_planner.plan_broll_for_creatomate(
        _make_dg(50.0),
        density="low",
    )
    assert len(plan) >= 1
    for item in plan:
        # Fallback prompts must be neutral
        assert "documents" in item["query_en"].lower() or "office" in item["query_en"].lower()


@pytest.mark.asyncio
async def test_plan_short_video_raises():
    with pytest.raises(broll_planner.BrollPlannerError):
        await broll_planner.plan_broll_for_creatomate(
            _make_dg(10.0, n_sentences=3),
        )


@pytest.mark.asyncio
async def test_plan_density_affects_count(monkeypatch):
    async def _fake_llm(model, system, user):
        return {i: {"query_en": "x", "query_ru": "икс", "prompt": "p"} for i in range(20)}, 1, 1
    monkeypatch.setattr(broll_planner, "_call_gemini_json_rows", _fake_llm)
    monkeypatch.setattr(broll_planner, "_gemini_cost", lambda *a, **kw: 0)

    low,  _ = await broll_planner.plan_broll_for_creatomate(_make_dg(60.0, 12), density="low")
    high, _ = await broll_planner.plan_broll_for_creatomate(_make_dg(60.0, 12), density="high")
    assert len(high) >= len(low)
