from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.gateways.mcp import MCPGatewayClient, MCPGatewayError


def test_mcp_client_initializes_once_and_parses_json_tool_result() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        methods.append(body["method"])
        if body["method"] == "initialize":
            result = {"serverInfo": {"name": "test"}}
        elif body["method"] == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "lookup",
                        "description": "Lookup a record",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            }
        else:
            result = {"structuredContent": {"result": {"count": 1}}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": result})

    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = MCPGatewayClient("http://gateway.test/mcp", 1, client=raw_client)
    tools = asyncio.run(client.list_tools("request-1"))
    first = asyncio.run(client.call_tool("lookup", {}, "request-1"))
    second = asyncio.run(client.call_tool("lookup", {}, "request-1"))
    asyncio.run(client.close())
    assert first == second == {"count": 1}
    assert tools[0].name == "lookup"
    assert tools[0].input_schema["type"] == "object"
    assert methods == ["initialize", "tools/list", "tools/call", "tools/call"]


def test_mcp_client_parses_sse_and_surfaces_rpc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = ({"jsonrpc": "2.0", "id": "1", "result": {"serverInfo": {}}} if body["method"] == "initialize" else {"jsonrpc": "2.0", "id": "2", "error": {"message": "denied"}})
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=f"event: message\ndata: {json.dumps(payload)}\n\n")

    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = MCPGatewayClient("http://gateway.test/mcp", 1, client=raw_client)
    with pytest.raises(MCPGatewayError, match="denied"):
        asyncio.run(client.call_tool("lookup", {}, "request-2"))
    asyncio.run(client.close())
