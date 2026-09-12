from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models import SemanticSynthesisOutput
from app.synthesizer import OpenAISemanticSynthesizer
from tests.fixtures import request_payload


class FakeResponses:
    def __init__(self) -> None:
        self.arguments = {}

    async def parse(self, **kwargs):
        self.arguments = kwargs
        return SimpleNamespace(
            output_parsed=SemanticSynthesisOutput(
                outcome="NO_PATTERN", reason="Test adapter output"
            )
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_openai_uses_responses_structured_output_without_storage() -> None:
    client = FakeOpenAIClient()
    adapter = OpenAISemanticSynthesizer(
        "", "test-model", max_output_tokens=777, client=client  # type: ignore[arg-type]
    )
    result = await adapter.synthesize(request_payload())
    await adapter.close()

    assert result.outcome == "NO_PATTERN"
    assert client.responses.arguments["text_format"] is SemanticSynthesisOutput
    assert client.responses.arguments["store"] is False
    assert client.responses.arguments["max_output_tokens"] == 777
    sent = json.loads(client.responses.arguments["input"][0]["content"])
    assert sent["synthesis_id"] == "SYN-conditional-discount-001"
    assert client.closed is True
