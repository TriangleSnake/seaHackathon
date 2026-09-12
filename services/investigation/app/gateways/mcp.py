"""Small stateless MCP client for the shared Agent Gateway."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.domain.models import ToolDefinition


class MCPGatewayError(RuntimeError):
    """Raised when a gateway request or tool execution fails."""


class MCPGatewayClient:
    def __init__(
        self,
        url: str,
        timeout_seconds: float,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._url = url
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._initialized = False

    async def close(self) -> None:
        await self._client.aclose()

    async def initialize(self, request_id: str, traceparent: Optional[str] = None) -> None:
        if self._initialized:
            return
        await self._request(
            {
                "jsonrpc": "2.0",
                "id": f"{request_id}:initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "investigation", "version": "0.2.0"},
                },
            },
            request_id,
            traceparent,
        )
        self._initialized = True

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        request_id: str,
        traceparent: Optional[str] = None,
    ) -> dict[str, Any]:
        await self.initialize(request_id, traceparent)
        result = await self._request(
            {
                "jsonrpc": "2.0",
                "id": f"{request_id}:{name}",
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            request_id,
            traceparent,
        )
        if result.get("isError"):
            raise MCPGatewayError(f"tool {name} returned an error")
        return self._tool_payload(result)

    async def list_tools(
        self,
        request_id: str,
        traceparent: Optional[str] = None,
    ) -> list[ToolDefinition]:
        """Discover the gateway contract so agents receive current tool schemas."""
        await self.initialize(request_id, traceparent)
        result = await self._request(
            {
                "jsonrpc": "2.0",
                "id": f"{request_id}:tools-list",
                "method": "tools/list",
                "params": {},
            },
            request_id,
            traceparent,
        )
        definitions: list[ToolDefinition] = []
        for item in result.get("tools", []):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            schema = item.get("inputSchema", {})
            definitions.append(
                ToolDefinition(
                    name=item["name"],
                    description=str(item.get("description", "")),
                    input_schema=schema if isinstance(schema, dict) else {},
                )
            )
        return definitions

    async def _request(
        self,
        payload: dict[str, Any],
        request_id: str,
        traceparent: Optional[str],
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        }
        if traceparent:
            headers["traceparent"] = traceparent
        try:
            response = await self._client.post(self._url, headers=headers, json=payload)
            response.raise_for_status()
            body = self._decode_response(response)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise MCPGatewayError("Agent Gateway request failed") from exc
        if "error" in body:
            error = body["error"]
            message = error.get("message", "unknown JSON-RPC error")
            raise MCPGatewayError(str(message))
        result = body.get("result")
        if not isinstance(result, dict):
            raise MCPGatewayError("Agent Gateway response has no result")
        return result

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        if "text/event-stream" not in response.headers.get("content-type", ""):
            decoded = response.json()
            if not isinstance(decoded, dict):
                raise ValueError("MCP response is not an object")
            return decoded
        events = []
        for line in response.text.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line.removeprefix("data:").strip()))
        if not events or not isinstance(events[-1], dict):
            raise ValueError("empty MCP event stream")
        return events[-1]

    @staticmethod
    def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            nested = structured.get("result")
            return nested if isinstance(nested, dict) else structured
        for item in result.get("content", []):
            if item.get("type") == "text":
                decoded = json.loads(item.get("text", ""))
                if isinstance(decoded, dict):
                    return decoded
        raise MCPGatewayError("tool returned no structured payload")
