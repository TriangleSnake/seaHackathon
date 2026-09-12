"""OpenAI Responses API adapter with schema-constrained specialist output."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional, Protocol, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.domain.models import AgentAnalysis, AgentRun, ToolCallResult, ToolDefinition
from app.runtime import model_override, reasoning_override


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


class AgentAnalysisError(RuntimeError):
    """Raised when a specialist cannot produce a valid structured result."""


class Analyzer(Protocol):
    async def analyze(
        self,
        agent: str,
        prompt: str,
        context: dict[str, Any],
        max_output_tokens: int,
        tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
        max_tool_calls: int,
    ) -> AgentRun: ...


class OpenAIAnalyzer:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 30,
        client: Optional[AsyncOpenAI] = None,
    ) -> None:
        if not api_key and client is None:
            raise AgentAnalysisError("OPENAI_API_KEY is not configured")
        self._client = client or AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    async def close(self) -> None:
        await self._client.close()

    async def generate_structured(
        self,
        instructions: str,
        context: dict[str, Any],
        output_model: type[StructuredOutput],
        max_output_tokens: int,
    ) -> tuple[StructuredOutput, int, int]:
        """Generate one schema-constrained result without exposing specialist tools."""
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=instructions,
                input=[
                    {
                        "role": "user",
                        "content": json.dumps(context, default=str, ensure_ascii=False),
                    }
                ],
                text_format=output_model,
                max_output_tokens=max_output_tokens,
                store=False,
            )
        except Exception as exc:
            raise AgentAnalysisError("orchestrator model request failed") from exc
        parsed = response.output_parsed
        if parsed is None:
            raise AgentAnalysisError("orchestrator returned no parsed output")
        usage = response.usage
        return (
            parsed,
            getattr(usage, "input_tokens", 0) if usage else 0,
            getattr(usage, "output_tokens", 0) if usage else 0,
        )

    async def analyze(
        self,
        agent: str,
        prompt: str,
        context: dict[str, Any],
        max_output_tokens: int,
        tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
        max_tool_calls: int,
    ) -> AgentRun:
        allowed = {tool.name for tool in tools}
        tool_specs = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
                # MCP schemas contain optional fields that are not strict-mode shaped.
                "strict": False,
            }
            for tool in tools
        ]
        input_items: list[Any] = [
            {
                "role": "user",
                "content": json.dumps(context, default=str, ensure_ascii=False),
            }
        ]
        call_results: list[ToolCallResult] = []
        input_tokens = 0
        output_tokens = 0

        # One final model turn is always allowed after the tool budget is consumed.
        for _ in range(max_tool_calls + 1):
            active_tools = tool_specs if len(call_results) < max_tool_calls else []
            request: dict[str, Any] = {
                "model": model_override.get() or self._model,
                "instructions": prompt,
                "input": input_items,
                "text_format": AgentAnalysis,
                "max_output_tokens": max_output_tokens,
                "store": False,
            }
            if reasoning_override.get() not in {None, "none"}:
                request["reasoning"] = {"effort": reasoning_override.get()}
            if active_tools:
                request.update(
                    tools=active_tools,
                    tool_choice="auto",
                    parallel_tool_calls=False,
                )
            try:
                response = await self._client.responses.parse(**request)
            except Exception as exc:
                raise AgentAnalysisError(f"{agent} model request failed") from exc

            usage = response.usage
            input_tokens += getattr(usage, "input_tokens", 0) if usage else 0
            output_tokens += getattr(usage, "output_tokens", 0) if usage else 0
            function_calls = [
                item
                for item in getattr(response, "output", [])
                if getattr(item, "type", None) == "function_call"
            ]
            if not function_calls:
                analysis = response.output_parsed
                if analysis is None:
                    raise AgentAnalysisError(f"{agent} returned no parsed output")
                return AgentRun(
                    agent=agent,
                    analysis=analysis,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    tool_calls=call_results,
                )

            input_items.extend(response.output)
            for call in function_calls:
                name = str(call.name)
                arguments: dict[str, Any] = {}
                payload: Optional[dict[str, Any]] = None
                error: Optional[str] = None
                try:
                    decoded = json.loads(call.arguments)
                    if not isinstance(decoded, dict):
                        raise ValueError("arguments must be a JSON object")
                    arguments = decoded
                    if name not in allowed:
                        raise ValueError("tool is not allowed for this agent")
                    if len(call_results) >= max_tool_calls:
                        raise ValueError("agent tool-call budget exhausted")
                    payload = await execute_tool(name, arguments)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                call_results.append(
                    ToolCallResult(
                        name=name,
                        arguments=arguments,
                        succeeded=payload is not None,
                        payload=payload,
                        error=error,
                    )
                )
                output = payload if payload is not None else {"error": error}
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(output, default=str, ensure_ascii=False),
                    }
                )

        raise AgentAnalysisError(f"{agent} exceeded its tool-call loop budget")


class UnavailableAnalyzer:
    """Keeps liveness/readiness available while reporting missing LLM configuration."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def close(self) -> None:
        return None

    async def generate_structured(
        self,
        instructions: str,
        context: dict[str, Any],
        output_model: type[StructuredOutput],
        max_output_tokens: int,
    ) -> tuple[StructuredOutput, int, int]:
        del instructions, context, output_model, max_output_tokens
        raise AgentAnalysisError(f"orchestrator unavailable: {self._reason}")

    async def analyze(
        self,
        agent: str,
        prompt: str,
        context: dict[str, Any],
        max_output_tokens: int,
        tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
        max_tool_calls: int,
    ) -> AgentRun:
        del prompt, context, max_output_tokens, tools, execute_tool, max_tool_calls
        raise AgentAnalysisError(f"{agent} unavailable: {self._reason}")
