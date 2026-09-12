from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi.testclient import TestClient

from app.agents import ChatAgent, MarketplaceInfoAgent, OrderAgent
from app.api.readiness import ReadinessError
from app.core.orchestrator import InvestigationOrchestrator
from app.domain.models import (
    AgentAnalysis,
    AgentItemScore,
    AgentRun,
    Finding,
    ToolCallResult,
    ToolDefinition,
)
from app.main import create_app
from app.policies.repository import FilePolicyRepository
from app.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


class ReadyProbe:
    async def check(self, request_id: str) -> None:
        assert request_id

    async def close(self) -> None:
        return None


class UnreadyProbe(ReadyProbe):
    async def check(self, request_id: str) -> None:
        raise ReadinessError("offline")


class FakeGateway:
    async def list_tools(
        self,
        request_id: str,
        traceparent: Optional[str] = None,
    ) -> list[ToolDefinition]:
        del traceparent
        assert request_id
        return [
            ToolDefinition(
                name="get_evidence_records",
                description="Resolve evidence records",
                input_schema={"type": "object", "properties": {}},
            )
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        request_id: str,
        traceparent: Optional[str] = None,
    ) -> dict[str, Any]:
        assert request_id
        assert isinstance(arguments, dict)
        del traceparent
        if name == "get_evidence_records":
            return {
                "found": True,
                "transaction": {"id": "TXN-0001", "status": "paid"},
                "payment_attempts": [
                    {"id": "PAY-0001", "status": "authorized"}
                ],
                "messages": [],
                "reports": [],
            }
        return {"count": 0, "matches": []}


class FakeAnalyzer:
    async def analyze(
        self,
        agent: str,
        prompt: str,
        context: dict[str, Any],
        max_output_tokens: int,
        tools: list[ToolDefinition],
        execute_tool: Any,
        max_tool_calls: int,
    ) -> AgentRun:
        assert prompt and max_output_tokens > 0
        findings = []
        tool_calls = []
        if agent == "order":
            assert [tool.name for tool in tools] == ["get_evidence_records"]
            assert max_tool_calls > 0
            payload = await execute_tool(
                "get_evidence_records", {"evidence_ids": ["TXN-0001"]}
            )
            tool_calls = [
                ToolCallResult(
                    name="get_evidence_records",
                    arguments={"evidence_ids": ["TXN-0001"]},
                    succeeded=True,
                    payload=payload,
                )
            ]
            assert "PAY-0001" in context["allowed_evidence_refs"]
            findings = [
                Finding(
                    type="payment_signal",
                    description="The order has a payment signal requiring review.",
                    impact="supports_fraud",
                    confidence=0.9,
                    evidence_refs=["PAY-0001"],
                )
            ]
        return AgentRun(
            agent=agent,
            analysis=AgentAnalysis(
                summary=f"{agent} complete",
                findings=findings,
                item_scores=(
                    [
                        AgentItemScore(
                            item_type="payment_activity",
                            score=0.68,
                            confidence=0.9,
                            rationale="Payment evidence requires review.",
                            evidence_refs=["PAY-0001"],
                        )
                    ]
                    if agent == "order"
                    else []
                ),
            ),
            input_tokens=100,
            output_tokens=50,
            tool_calls=tool_calls,
        )

    async def close(self) -> None:
        return None


def make_orchestrator() -> InvestigationOrchestrator:
    analyzer = FakeAnalyzer()
    prompts = ROOT / "app" / "prompts"
    agents = [
        OrderAgent(analyzer, prompts / "order.md"),
        ChatAgent(analyzer, prompts / "chat.md"),
        MarketplaceInfoAgent(analyzer, prompts / "marketplace_info.md"),
    ]
    return InvestigationOrchestrator(
        FakeGateway(),
        FilePolicyRepository(str(ROOT / "config" / "scoreboard.development.json")),
        agents,
    )


def test_production_agent_registry_matches_architecture() -> None:
    assert make_orchestrator().agent_names == (
        "order",
        "chat",
        "marketplace_info",
    )


def make_client(probe: Optional[ReadyProbe] = None) -> TestClient:
    settings = Settings(
        service_name="test-investigation",
        agentgateway_url="http://gateway.test/mcp",
        gateway_timeout_seconds=1,
        policy_path=str(ROOT / "config" / "scoreboard.development.json"),
    )
    app = create_app(settings, readiness_probe=probe, orchestrator=make_orchestrator())
    return TestClient(app)


def valid_request() -> dict[str, Any]:
    return {
        "case_id": "case-001",
        "detection_result": {
            "detection_id": "detection-001",
            "subject": {"type": "transaction", "id": "TXN-0001"},
            "detected": True,
            "triggers": [
                {
                    "type": "payment_anomaly",
                    "detector": "rule_based",
                    "reason": "Payment pattern requires order investigation",
                    "evidence_refs": ["PAY-0001"],
                }
            ],
            "evidence": [
                {
                    "id": "PAY-0001",
                    "source": "detection",
                    "type": "payment_attempt",
                    "data": {"status": "authorized"},
                }
            ],
        },
        "scoreboard_config_ref": {"version": "development-v1"},
    }


def test_health_and_generated_request_id() -> None:
    with make_client() as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "test-investigation"}
    assert response.headers["X-Request-ID"]


def test_ready_checks_dependencies_and_preserves_request_id() -> None:
    with make_client(ReadyProbe()) as client:
        response = client.get("/ready", headers={"X-Request-ID": "request-123"})
    assert response.status_code == 200
    assert response.json()["dependencies"] == {
        "agentgateway": "ok",
        "database": "ok",
    }
    assert response.headers["X-Request-ID"] == "request-123"


def test_ready_returns_503_when_dependency_is_down() -> None:
    with make_client(UnreadyProbe()) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"


def test_investigate_runs_agents_and_returns_scoreboard() -> None:
    with make_client() as client:
        response = client.post("/investigate", json=valid_request())
    body = response.json()
    assert response.status_code == 200
    assert "X-Investigation-Placeholder" not in response.headers
    assert body["verdict"] == "suspicious"
    assert body["findings"][0]["evidence_refs"] == ["PAY-0001"]
    assert body["scoreboard"]["fraud_score"] == 0.68
    assert body["scoreboard"]["usage"]["tool_calls"] == 1
    assert body["scoreboard"]["scoring_policy_version"] == "specialist-weighted-v1"
    assert body["agents_invoked"][0]["agent"] == "order"
    assert body["agents_invoked"][0]["case_type"] == "order"
    assert body["agent_results"][0]["raw_analysis"]["item_scores"][0]["score"] == 0.68
    assert body["agent_results"][0]["score_aggregate"]["weighted_score"] == 0.68


def test_investigate_rejects_unknown_request_fields() -> None:
    payload = valid_request()
    payload["unexpected"] = True
    with make_client() as client:
        response = client.post("/investigate", json=payload)
    assert response.status_code == 422


def test_investigate_rejects_unknown_scoreboard_reference() -> None:
    payload = valid_request()
    payload["scoreboard_config_ref"] = {"version": "does-not-exist"}
    with make_client() as client:
        response = client.post("/investigate", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "scoreboard_config_not_found"


def test_investigate_rejects_empty_scoreboard_reference() -> None:
    payload = valid_request()
    payload["scoreboard_config_ref"] = {}
    with make_client() as client:
        response = client.post("/investigate", json=payload)
    assert response.status_code == 422
