from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi.testclient import TestClient

from app.agents import ChatAgent, MarketplaceInfoAgent, OrchestratorAgent, OrderAgent
from app.api.readiness import ReadinessError
from app.core.orchestrator import InvestigationOrchestrator
from app.domain.models import (
    AgentAnalysis,
    AgentItemScore,
    AgentRun,
    Finding,
    OrchestratorDecision,
    OrchestratorReport,
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
    def __init__(self) -> None:
        self.orchestrator_decisions = 0

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
        assert context["score_items"]
        assert all(isinstance(item, str) for item in context["score_items"])
        assert set(context["score_scale"]) == {"0", "1", "2", "3", "4", "5"}
        assert "is_direct_evidence=true" in context["score_scale"]["5"]
        assert context["output_language"] == "Traditional Chinese (zh-TW)"
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
                            score=3,
                            is_direct_evidence=False,
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

    async def generate_structured(
        self,
        instructions: str,
        context: dict[str, Any],
        output_model: type[Any],
        max_output_tokens: int,
    ) -> tuple[Any, int, int]:
        assert instructions and max_output_tokens > 0
        if output_model is OrchestratorDecision:
            self.orchestrator_decisions += 1
            if context["specialist_results"]:
                return (
                    OrchestratorDecision(
                        action="stop", reason="訂單調查結果已足夠。"
                    ),
                    10,
                    5,
                )
            return (
                OrchestratorDecision(
                    action="invoke_agent",
                    agent="order",
                    reason="先調查付款活動。",
                    investigation_focus=["付款活動"],
                ),
                10,
                5,
            )
        assert output_model is OrchestratorReport
        return (
            OrchestratorReport(
                summary="Orchestrator 已整合訂單調查結果。",
            ),
            10,
            5,
        )


def make_orchestrator() -> InvestigationOrchestrator:
    analyzer = FakeAnalyzer()
    prompts = ROOT / "app" / "prompts"
    agents = [
        OrderAgent(analyzer, prompts / "order.md"),
        ChatAgent(analyzer, prompts / "chat.md"),
        MarketplaceInfoAgent(analyzer, prompts / "marketplace_info.md"),
    ]
    orchestrator_agent = OrchestratorAgent(
        analyzer, prompts / "orchestrator.md"
    )
    return InvestigationOrchestrator(
        FakeGateway(),
        FilePolicyRepository(str(ROOT / "config" / "scoreboard.development.json")),
        agents,
        orchestrator_agent=orchestrator_agent,
    )


def test_production_agent_registry_matches_architecture() -> None:
    orchestrator = make_orchestrator()
    assert orchestrator.orchestrator_name == "orchestrator"
    assert orchestrator.agent_names == (
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
    assert set(body) == {
        "case_id",
        "subject",
        "verdict",
        "confidence",
        "summary",
        "findings",
        "evidence",
        "agents_invoked",
        "agent_results",
        "scoreboard",
        "stop_reason",
    }
    assert "X-Investigation-Placeholder" not in response.headers
    assert body["verdict"] == "suspicious"
    assert body["findings"][0]["evidence_refs"] == ["PAY-0001"]
    assert body["scoreboard"]["fraud_score"] == 0.6
    assert body["scoreboard"]["usage"]["tool_calls"] == 1
    assert body["scoreboard"]["scoring_policy_version"] == "specialist-weighted-v1"
    assert body["agents_invoked"][0]["agent"] == "order"
    assert body["agents_invoked"][0]["case_type"] == "order"
    assert body["agent_results"][0]["raw_analysis"]["item_scores"][0]["score"] == 3
    assert body["agent_results"][0]["score_aggregate"]["weighted_score"] == 0.6
    assert body["summary"] == "Orchestrator 已整合訂單調查結果。"
    assert "啟動調查" in body["agents_invoked"][0]["reason"]


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
