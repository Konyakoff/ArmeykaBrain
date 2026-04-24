"""ClaudeProvider — тонкая обёртка над app/services/claude_service.py."""

from __future__ import annotations

from app.models.schemas import Step1Result, Step2Result, Step3Result
from app.services import claude_service as _c


class ClaudeProvider:
    name = "claude"

    async def top_ids(self, question: str, model: str) -> Step1Result:
        return await _c.get_top_ids_claude(question, model)

    async def expert_analysis(
        self,
        question: str,
        combined_context: str,
        style: str = "telegram_yur",
        max_length: int = 4000,
        override_style: str | None = None,
        model: str = "",
    ) -> Step2Result:
        return await _c.get_expert_analysis_claude(
            question, combined_context,
            style=style, max_length=max_length,
            override_style=override_style,
            model_name=model or "claude-sonnet-4-6",
        )

    async def audio_script(
        self,
        expert_answer: str,
        duration: int,
        wpm: int = 150,
        override: str | None = None,
        model: str = "",
    ) -> Step3Result:
        return await _c.generate_audio_script_claude(
            expert_answer, duration=duration, wpm=wpm,
            override=override,
            model_name=model or "claude-haiku-4-5",
        )

    def calculate_cost(self, in_tokens: int, out_tokens: int, model: str) -> tuple[float, float]:
        return _c.calculate_claude_cost(in_tokens, out_tokens, model)
