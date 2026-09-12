from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.domain.models import AgentAnalysis, ToolDefinition
from app.gateways.openai import OpenAIAnalyzer


class FakeResponses:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> Any:
        self.arguments = kwargs
        return SimpleNamespace(
            output_parsed=AgentAnalysis(summary="No supported findings."),
            output=[],
            usage=SimpleNamespace(input_tokens=12, output_tokens=5),
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_openai_adapter_uses_structured_non_stored_response() -> None:
    client = FakeOpenAIClient()
    analyzer = OpenAIAnalyzer("", "test-model", client=client)  # type: ignore[arg-type]
    async def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(f"unexpected tool call: {name} {arguments}")

    result = asyncio.run(
        analyzer.analyze("order", "prompt", {"evidence": []}, 321, [], execute_tool, 0)
    )
    asyncio.run(analyzer.close())
    assert result.input_tokens == 12
    assert result.output_tokens == 5
    assert client.responses.arguments["text_format"] is AgentAnalysis
    assert client.responses.arguments["store"] is False
    assert client.responses.arguments["max_output_tokens"] == 321
    assert client.closed is True


class ToolLoopResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                output_parsed=None,
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_transaction_context",
                        arguments='{"transaction_id":"TXN-1"}',
                        call_id="call-1",
                    )
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=3),
            )
        return SimpleNamespace(
            output_parsed=AgentAnalysis(summary="Tool evidence reviewed."),
            output=[],
            usage=SimpleNamespace(input_tokens=15, output_tokens=5),
        )


def test_openai_adapter_runs_model_selected_tool_loop() -> None:
    client = FakeOpenAIClient()
    client.responses = ToolLoopResponses()
    analyzer = OpenAIAnalyzer("", "test-model", client=client)  # type: ignore[arg-type]
    executed: list[tuple[str, dict[str, Any]]] = []

    async def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        executed.append((name, arguments))
        return {"transaction": {"id": "TXN-1"}}

    result = asyncio.run(
        analyzer.analyze(
            "order",
            "prompt",
            {"subject": {"type": "transaction", "id": "TXN-1"}},
            321,
            [
                ToolDefinition(
                    name="get_transaction_context",
                    description="Get transaction context",
                    input_schema={"type": "object", "properties": {}},
                )
            ],
            execute_tool,
            1,
        )
    )
    assert executed == [("get_transaction_context", {"transaction_id": "TXN-1"})]
    assert result.input_tokens == 25
    assert result.output_tokens == 8
    assert result.tool_calls[0].succeeded is True
    assert client.responses.calls[0]["parallel_tool_calls"] is False
    assert client.responses.calls[0]["tools"][0]["name"] == "get_transaction_context"
    assert "tools" not in client.responses.calls[1]
    assert client.responses.calls[1]["input"][-1]["type"] == "function_call_output"
