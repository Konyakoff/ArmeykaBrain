"""LLMProvider Protocol — единый интерфейс для всех LLM-провайдеров.

Делает невозможным забыть проверку модели в новом месте: оркестратор
больше не ветвится через _is_claude(...) на каждом шаге.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models.schemas import Step1Result, Step2Result, Step3Result


@runtime_checkable
class LLMProvider(Protocol):
    """Абстракция над одним LLM-провайдером (Gemini, Claude, …).

    Все методы async и возвращают Pydantic-модели из app/models/schemas.py,
    чтобы вызывающий код не зависел от формата конкретного SDK.
    """

    name: str

    async def top_ids(self, question: str, model: str) -> Step1Result:
        """Шаг 1: подбор статей НПА."""

    async def expert_analysis(
        self,
        question: str,
        combined_context: str,
        style: str = "telegram_yur",
        max_length: int = 4000,
        override_style: str | None = None,
        model: str = "",
    ) -> Step2Result:
        """Шаг 2: экспертная статья."""

    async def audio_script(
        self,
        expert_answer: str,
        duration: int,
        wpm: int = 150,
        override: str | None = None,
        model: str = "",
    ) -> Step3Result:
        """Шаг 3: аудиосценарий."""

    def calculate_cost(self, in_tokens: int, out_tokens: int, model: str) -> tuple[float, float]:
        """Возвращает (input_cost, output_cost) в USD."""
