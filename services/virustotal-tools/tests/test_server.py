from __future__ import annotations

import asyncio

from app.server import mcp


def test_mcp_exposes_one_bounded_reputation_tool() -> None:
    tools = asyncio.run(mcp.list_tools())
    assert [tool.name for tool in tools] == ["get_virustotal_reputation"]
    schema = tools[0].inputSchema
    assert schema["required"] == ["indicator_type", "indicator"]
    assert schema["properties"]["indicator_type"]["enum"] == ["url", "domain"]
    assert "ctx" not in schema["properties"]
