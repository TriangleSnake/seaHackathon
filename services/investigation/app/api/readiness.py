"""Operational readiness check for Agent Gateway and PostgreSQL."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx


class ReadinessError(RuntimeError):
    """Raised when a required dependency is unavailable."""


class GatewayReadinessProbe:
    def __init__(
        self,
        url: str,
        timeout_seconds: float,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._url = url
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def check(self, request_id: str) -> None:
        try:
            await self._request(
                {
                    "jsonrpc": "2.0",
                    "id": f"{request_id}:initialize",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "investigation-readiness",
                            "version": "0.1.0",
                        },
                    },
                },
                request_id,
            )
            result = await self._request(
                {
                    "jsonrpc": "2.0",
                    "id": f"{request_id}:database",
                    "method": "tools/call",
                    "params": {"name": "database_health", "arguments": {}},
                },
                request_id,
            )
            payload = self._tool_payload(result)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ReadinessError("agent gateway or database is unavailable") from exc

        if payload.get("ok") is not True:
            raise ReadinessError("database health check did not return ok")

    async def _request(self, payload: dict[str, Any], request_id: str) -> dict[str, Any]:
        response = await self._client.post(
            self._url,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "X-Request-ID": request_id,
            },
            json=payload,
        )
        response.raise_for_status()
        body = self._decode_response(response)
        if "error" in body:
            raise ReadinessError("agent gateway returned a JSON-RPC error")
        return body["result"]

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            return response.json()

        data_lines = [
            line.removeprefix("data:").strip()
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            raise ValueError("empty MCP event stream")
        return json.loads(data_lines[-1])

    @staticmethod
    def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
        if result.get("isError"):
            raise ReadinessError("database_health tool returned an error")

        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            nested = structured.get("result")
            return nested if isinstance(nested, dict) else structured

        for item in result.get("content", []):
            if item.get("type") == "text":
                decoded = json.loads(item["text"])
                if isinstance(decoded, dict):
                    return decoded
        raise ReadinessError("database_health returned no structured payload")
