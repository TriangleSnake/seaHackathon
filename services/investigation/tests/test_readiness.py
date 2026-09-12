from __future__ import annotations

import asyncio
import json

import httpx

from app.api.readiness import GatewayReadinessProbe, ReadinessError


def test_gateway_readiness_checks_database_health() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        methods.append(request_body["method"])
        if request_body["method"] == "initialize":
            result = {"serverInfo": {"name": "system-tools", "version": "1"}}
        else:
            result = {
                "structuredContent": {
                    "ok": True,
                    "database": "fraud_intelligence",
                }
            }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "test", "result": result})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    probe = GatewayReadinessProbe("http://gateway.test/mcp", 1, client=client)

    asyncio.run(probe.check("request-123"))
    asyncio.run(probe.close())

    assert methods == ["initialize", "tools/call"]


def test_gateway_readiness_rejects_unhealthy_database() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        result = (
            {"serverInfo": {"name": "system-tools", "version": "1"}}
            if request_body["method"] == "initialize"
            else {"structuredContent": {"ok": False}}
        )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "test", "result": result})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    probe = GatewayReadinessProbe("http://gateway.test/mcp", 1, client=client)

    try:
        asyncio.run(probe.check("request-456"))
    except ReadinessError as exc:
        assert "did not return ok" in str(exc)
    else:
        raise AssertionError("unhealthy database should fail readiness")
    finally:
        asyncio.run(probe.close())
