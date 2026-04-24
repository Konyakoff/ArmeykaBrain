"""Фабрика LLM-провайдеров.

Использование:
    from app.services.llm import get_provider
    provider = get_provider(model_name)
    step1 = await provider.top_ids(question, model_name)
    in_cost, out_cost = provider.calculate_cost(step1.in_tokens, step1.out_tokens, model_name)
"""

from __future__ import annotations

from app.services.llm.base import LLMProvider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.claude import ClaudeProvider

_GEMINI = GeminiProvider()
_CLAUDE = ClaudeProvider()


def get_provider(model: str) -> LLMProvider:
    """Возвращает провайдер по имени модели.

    Соглашение: модели Claude начинаются с 'claude-'. Всё остальное — Gemini.
    """
    if (model or "").startswith("claude-"):
        return _CLAUDE
    return _GEMINI


__all__ = ["LLMProvider", "GeminiProvider", "ClaudeProvider", "get_provider"]
