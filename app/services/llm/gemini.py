"""GeminiProvider — тонкая обёртка над app/services/gemini_service.py."""

from __future__ import annotations

from app.models.schemas import Step1Result, Step2Result, Step3Result
from app.services import gemini_service as _g


class GeminiProvider:
    name = "gemini"

    async def top_ids(self, question: str, model: str) -> Step1Result:
        return await _g.get_top_ids(question, model)

    async def expert_analysis(
        self,
        question: str,
        combined_context: str,
        style: str = "telegram_yur",
        max_length: int = 4000,
        override_style: str | None = None,
        model: str = "",
    ) -> Step2Result:
        # gemini_service.get_expert_analysis игнорирует параметр model:
        # он жёстко использует gemini-3.1-pro-preview внутри.
        return await _g.get_expert_analysis(
            question, combined_context, style=style,
            max_length=max_length, override_style=override_style,
        )

    async def audio_script(
        self,
        expert_answer: str,
        duration: int,
        wpm: int = 150,
        override: str | None = None,
        model: str = "",
    ) -> Step3Result:
        return await _g.generate_audio_script(
            expert_answer, duration=duration, wpm=wpm, override=override,
        )

    def calculate_cost(self, in_tokens: int, out_tokens: int, model: str) -> tuple[float, float]:
        return _g.calculate_cost(in_tokens, out_tokens, model)
