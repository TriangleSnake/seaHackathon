from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from app.core.orchestrator import InvestigationOrchestrator
from app.agents import ChatAgent, MarketplaceInfoAgent, OrderAgent
from app.domain.models import (
    AgentAnalysis,
    AgentItemScore,
    AgentRun,
    Finding,
    InvestigationRequest,
    ToolCallResult,
    ToolDefinition,
)
from app.policies.repository import FilePolicyRepository


ROOT = Path(__file__).resolve().parents[1]


class CaseGateway:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def list_tools(
        self,
        request_id: str,
        traceparent: Optional[str] = None,
    ) -> list[ToolDefinition]:
        del request_id, traceparent
        if self.fail:
            raise RuntimeError("offline")
        return [
            ToolDefinition(
                name="get_previous_cases",
                description="Get previous cases",
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
        del arguments, request_id, traceparent
        if self.fail:
            raise RuntimeError("offline")
        if name == "get_previous_cases":
            return {
                "count": 1,
                "cases": [{"id": "prior-fraud-case", "status": "confirmed_fraud"}],
            }
        return {"count": 0}


class DirectEvidenceAgent:
    name = "order"
    item_score_weights = {"account_activity": 1.0}

    def routing_score(self, subject: Any, evidence: Any, trigger_text: str) -> int:
        del subject, evidence, trigger_text
        return 10

    def relevance(self, subject: Any, evidence: Any, trigger_text: str) -> int:
        del subject, evidence, trigger_text
        return 10

    async def run(
        self,
        subject: Any,
        evidence: Any,
        trigger_text: str,
        max_output_tokens: int,
        gateway_tools: list[ToolDefinition],
        execute_tool: Any,
        max_tool_calls: int,
    ) -> AgentRun:
        del evidence, trigger_text, max_output_tokens
        assert gateway_tools[0].name == "get_previous_cases"
        assert max_tool_calls > 0
        payload = await execute_tool(
            "get_previous_cases",
            {"subject_type": subject.type, "subject_id": subject.id, "limit": 20},
        )
        finding = Finding(
            type="confirmed_prior_fraud",
            description="A previous case confirmed fraud for this subject.",
            impact="supports_fraud",
            confidence=0.99,
            evidence_refs=["prior-fraud-case"],
        )
        return AgentRun(
            agent=self.name,
            analysis=AgentAnalysis(
                summary="Confirmed prior fraud case.",
                findings=[finding],
                item_scores=[
                    AgentItemScore(
                        item_type="account_activity",
                        score=5,
                        is_direct_evidence=True,
                        confidence=0.99,
                        rationale="A prior case confirmed fraud.",
                        evidence_refs=["prior-fraud-case"],
                    )
                ],
                direct_evidence_found=True,
            ),
            input_tokens=10,
            output_tokens=10,
            tool_calls=[
                ToolCallResult(
                    name="get_previous_cases",
                    arguments={
                        "subject_type": subject.type,
                        "subject_id": subject.id,
                        "limit": 20,
                    },
                    succeeded=True,
                    payload=payload,
                )
            ],
        )


def request() -> InvestigationRequest:
    return InvestigationRequest.model_validate(
        {
            "case_id": "case-new",
            "detection_result": {
                "detection_id": "detection-new",
                "subject": {"type": "account", "id": "acct-known-fraud"},
                "detected": True,
                "triggers": [],
                "evidence": [],
            },
            "scoreboard_config_ref": {"version": "development-v1"},
        }
    )


def request_for(subject_type: str, subject_id: str) -> InvestigationRequest:
    payload = request().model_dump()
    payload["detection_result"]["subject"] = {
        "type": subject_type,
        "id": subject_id,
    }
    return InvestigationRequest.model_validate(payload)


def repository() -> FilePolicyRepository:
    return FilePolicyRepository(str(ROOT / "config" / "scoreboard.development.json"))


def test_direct_evidence_stops_and_reaches_fraud_verdict() -> None:
    orchestrator = InvestigationOrchestrator(
        CaseGateway(), repository(), [DirectEvidenceAgent()]  # type: ignore[list-item]
    )
    result = asyncio.run(orchestrator.investigate(request(), "request-1"))
    assert result.stop_reason == "direct_evidence"
    assert result.verdict == "fraud"
    assert result.scoreboard["fraud_score"] == 1.0
    assert result.confidence == 1.0
    assert result.findings[0].evidence_refs == ["prior-fraud-case"]


def test_gateway_failures_are_reported_without_crashing() -> None:
    orchestrator = InvestigationOrchestrator(CaseGateway(fail=True), repository(), [])
    result = asyncio.run(orchestrator.investigate(request(), "request-2"))
    assert result.verdict == "unknown"
    assert result.stop_reason == "insufficient_evidence"
    assert result.summary == "調查已完成，但沒有足夠證據形成受支持的發現。"
    assert result.scoreboard["usage"]["tool_calls"] == 0


def test_specialists_have_role_scoped_tool_allowlists() -> None:
    common = {
        "get_evidence_records",
        "get_environment_overview",
        "get_account_activity",
        "find_shared_ip_accounts",
        "find_shared_device_accounts",
        "get_entity_neighbors",
        "get_previous_cases",
    }
    assert common.issubset(OrderAgent.allowed_tools)
    assert common.issubset(ChatAgent.allowed_tools)
    assert common.issubset(MarketplaceInfoAgent.allowed_tools)
    assert "get_account_commerce_links" in OrderAgent.allowed_tools
    assert "find_shared_payment_instrument_accounts" in OrderAgent.allowed_tools
    assert "find_conversation_accounts" in ChatAgent.allowed_tools
    assert "find_accounts_by_indicator" in ChatAgent.allowed_tools
    assert "get_virustotal_reputation" in ChatAgent.allowed_tools
    assert "get_virustotal_reputation" not in OrderAgent.allowed_tools
    assert "get_virustotal_reputation" not in MarketplaceInfoAgent.allowed_tools
    assert "get_subject_association_seeds" in MarketplaceInfoAgent.allowed_tools
    assert "find_reused_product_image_accounts" in MarketplaceInfoAgent.allowed_tools
    for agent in (OrderAgent, ChatAgent, MarketplaceInfoAgent):
        assert "database_health" not in agent.allowed_tools
        assert "search_accounts" not in agent.allowed_tools


def test_orchestrator_prioritizes_case_type_from_subject() -> None:
    analyzer = object()
    prompts = ROOT / "app" / "prompts"
    agents = [
        MarketplaceInfoAgent(analyzer, prompts / "marketplace_info.md"),  # type: ignore[arg-type]
        ChatAgent(analyzer, prompts / "chat.md"),  # type: ignore[arg-type]
        OrderAgent(analyzer, prompts / "order.md"),  # type: ignore[arg-type]
    ]
    orchestrator = InvestigationOrchestrator(CaseGateway(), repository(), agents)  # type: ignore[arg-type]
    priorities = repository().resolve(
        request().scoreboard_config_ref
    ).agent_priorities
    cases = {
        "transaction": "order",
        "message": "chat",
        "product": "marketplace_info",
    }
    for subject_type, expected_agent in cases.items():
        subject = request_for(subject_type, f"id-{subject_type}").detection_result.subject
        ranked = orchestrator._rank_agents(subject, [], "", priorities)
        assert ranked[0].name == expected_agent
