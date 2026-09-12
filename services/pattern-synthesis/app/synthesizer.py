"""Semantic synthesis adapters; provenance enforcement lives elsewhere."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from openai import AsyncOpenAI

from .errors import SynthesisError, SynthesisUnavailableError
from .models import SemanticSynthesisOutput


DEFAULT_PROMPT_PATH = Path(__file__).parent / "prompts" / "pattern_synthesis.md"


class SemanticSynthesizer(Protocol):
    available: bool

    async def synthesize(self, context: Mapping[str, Any]) -> SemanticSynthesisOutput: ...

    async def close(self) -> None: ...


class OpenAISemanticSynthesizer:
    available = True

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 30,
        max_output_tokens: int = 3000,
        prompt_path: Path = DEFAULT_PROMPT_PATH,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not api_key and client is None:
            raise SynthesisUnavailableError("OPENAI_API_KEY is not configured")
        self._client = client or AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._instructions = prompt_path.read_text(encoding="utf-8")

    async def synthesize(self, context: Mapping[str, Any]) -> SemanticSynthesisOutput:
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=self._instructions,
                input=[
                    {
                        "role": "user",
                        "content": json.dumps(context, ensure_ascii=False, default=str),
                    }
                ],
                text_format=SemanticSynthesisOutput,
                max_output_tokens=self._max_output_tokens,
                store=False,
            )
        except Exception as exc:
            raise SynthesisError(
                "semantic_synthesis_failed", "OpenAI semantic synthesis failed"
            ) from exc
        parsed = response.output_parsed
        if parsed is None:
            raise SynthesisError(
                "semantic_synthesis_failed", "OpenAI returned no parsed synthesis"
            )
        return parsed

    async def close(self) -> None:
        await self._client.close()


class UnavailableSemanticSynthesizer:
    available = False

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def synthesize(self, context: Mapping[str, Any]) -> SemanticSynthesisOutput:
        del context
        raise SynthesisUnavailableError(self._reason)

    async def close(self) -> None:
        return None
