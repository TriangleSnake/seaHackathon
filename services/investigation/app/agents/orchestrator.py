"""LLM agent that plans specialist work and synthesizes the final report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.domain.models import OrchestratorDecision, OrchestratorReport


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


class StructuredGenerator(Protocol):
    async def generate_structured(
        self,
        instructions: str,
        context: dict[str, Any],
        output_model: type[StructuredOutput],
        max_output_tokens: int,
    ) -> tuple[StructuredOutput, int, int]: ...


class OrchestratorAgent:
    name = "orchestrator"

    def __init__(self, generator: StructuredGenerator, prompt_path: Path) -> None:
        self._generator = generator
        self._prompt = prompt_path.read_text(encoding="utf-8")

    async def decide(
        self, context: dict[str, Any], max_output_tokens: int
    ) -> tuple[OrchestratorDecision, int, int]:
        return await self._generator.generate_structured(
            self._prompt,
            {"task": "plan_next_step", **context},
            OrchestratorDecision,
            max_output_tokens,
        )

    async def report(
        self, context: dict[str, Any], max_output_tokens: int
    ) -> tuple[OrchestratorReport, int, int]:
        return await self._generator.generate_structured(
            self._prompt,
            {"task": "write_final_report", **context},
            OrchestratorReport,
            max_output_tokens,
        )
