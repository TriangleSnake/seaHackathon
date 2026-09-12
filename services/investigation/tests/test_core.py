from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.models import (
    AgentAnalysis,
    AgentItemScore,
    Evidence,
    Finding,
    ScoreboardConfigRef,
    Subject,
)
from app.agents.order import OrderAgent
from app.agents.chat import ChatAgent
from app.evidence.ledger import EvidenceLedger
from app.policies.repository import FilePolicyRepository, PolicyNotFoundError
from app.scoring.engine import apply_findings, confidence_for, verdict_for
from app.scoring.weighted import AgentScoreAggregator, combine_agent_scores


ROOT = Path(__file__).resolve().parents[1]


class UnusedAnalyzer:
    async def analyze(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("not used")


def test_evidence_ledger_deduplicates_and_rejects_unknown_citations() -> None:
    evidence = Evidence(id="e-1", source="detection", type="login", data={})
    ledger = EvidenceLedger([evidence, evidence])
    ledger.add_tool_result("tool-1", "lookup", {"rows": [{"id": "row-1", "x": 1}]})
    valid = Finding(
        type="signal",
        description="supported",
        impact="supports_fraud",
        confidence=1,
        evidence_refs=["row-1"],
    )
    invalid = valid.model_copy(update={"evidence_refs": ["invented"]})
    accepted, rejected = ledger.validate_findings([valid, invalid])
    assert [item.id for item in ledger.items()] == ["e-1", "tool-1", "row-1"]
    assert accepted == [valid]
    assert rejected == 1


def test_virustotal_tool_records_are_external_citable_evidence() -> None:
    ledger = EvidenceLedger()
    ledger.add_tool_result(
        "tool-1",
        "get_virustotal_reputation",
        {
            "id": "VT-URL-1",
            "provider": "virustotal",
            "found": True,
            "report": {"object_id": "vt-object-1", "type": "url"},
        },
    )
    indexed = {item.id: item for item in ledger.items()}
    assert indexed["VT-URL-1"].source == "external"
    assert "vt-object-1" not in indexed


def test_deterministic_scoring_and_verdict() -> None:
    config = FilePolicyRepository(
        str(ROOT / "config" / "scoreboard.development.json")
    ).resolve(ScoreboardConfigRef(version="development-v1"))
    findings = [
        Finding(type="fraud", description="fraud signal", impact="supports_fraud", confidence=1, evidence_refs=["e-1"]),
        Finding(type="legitimate", description="legitimate signal", impact="supports_legitimate", confidence=0.25, evidence_refs=["e-2"]),
    ]
    score, delta = apply_findings(0.5, findings, config)
    assert score == pytest.approx(0.65)
    assert delta == pytest.approx(0.15)
    assert verdict_for(score, config, True) == "suspicious"
    assert confidence_for(score, True) == pytest.approx(0.3)


def test_policy_repository_resolves_version_and_alias() -> None:
    repository = FilePolicyRepository(str(ROOT / "config" / "scoreboard.development.json"))
    assert repository.resolve(ScoreboardConfigRef(version="development-v1")).version == "development-v1"
    assert repository.resolve(ScoreboardConfigRef(version="default")).version == "development-v1"
    with pytest.raises(PolicyNotFoundError):
        repository.resolve(ScoreboardConfigRef(version="missing"))


def test_common_identity_evidence_is_context_not_a_routing_signal() -> None:
    agent = OrderAgent(UnusedAnalyzer(), ROOT / "app" / "prompts" / "order.md")
    account = Evidence(
        id="ACC-0001", source="environment", type="account", data={"status": "active"}
    )
    login = Evidence(
        id="LOG-0001", source="environment", type="login_event", data={}
    )
    assert agent.relevance(
        subject=Subject(type="account", id="ACC-0001"),
        evidence=[account, login],
        trigger_text="",
    ) == 0
    assert agent.select_evidence([account, login]) == [account, login]


def test_chat_prompt_exposes_guarded_virustotal_lookup() -> None:
    agent = ChatAgent(UnusedAnalyzer(), ROOT / "app" / "prompts" / "chat.md")
    assert "get_virustotal_reputation" in agent._prompt
    assert 'indicator_type="url"' in agent._prompt
    assert 'indicator_type="domain"' in agent._prompt
    assert "does not submit a new scan" in agent._prompt
    assert "currently unavailable" not in agent._prompt
    assert "Traditional Chinese (zh-TW)" in agent._prompt
    assert "Do not translate identifiers" in agent._prompt


def test_item_scores_are_evidence_bound_and_weighted_deterministically() -> None:
    analysis = AgentAnalysis(
        summary="Two order dimensions scored.",
        item_scores=[
            AgentItemScore(
                item_type="transaction_activity",
                score=4,
                is_direct_evidence=False,
                confidence=1.0,
                rationale="Transaction signal.",
                evidence_refs=["TXN-1"],
            ),
            AgentItemScore(
                item_type="account_activity",
                score=1,
                is_direct_evidence=False,
                confidence=0.5,
                rationale="Account counterevidence.",
                evidence_refs=["ACC-1"],
            ),
            AgentItemScore(
                item_type="payment_activity",
                score=5,
                is_direct_evidence=False,
                confidence=1.0,
                rationale="A five without direct evidence must be rejected.",
                evidence_refs=["PAY-1"],
            ),
        ],
    )
    result = AgentScoreAggregator().aggregate(
        "order",
        analysis,
        {
            "transaction_activity": 0.30,
            "payment_activity": 0.25,
            "account_activity": 0.15,
        },
        {"TXN-1", "ACC-1", "PAY-1"},
    )
    assert result.rejected_item_scores == 1
    assert result.raw_analysis is analysis
    assert result.score_aggregate is not None
    assert result.score_aggregate.weighted_score == pytest.approx(0.68)
    assert result.score_aggregate.coverage == pytest.approx(0.45 / 0.70)
    assert combine_agent_scores([result]) == pytest.approx(0.68)


def test_case_score_uses_highest_specialist_score() -> None:
    aggregator = AgentScoreAggregator()
    low = aggregator.aggregate(
        "chat",
        AgentAnalysis(summary="low", item_scores=[AgentItemScore(item_type="signal", score=1, is_direct_evidence=False, confidence=1.0, rationale="low", evidence_refs=["E-1"])]),
        {"signal": 1.0},
        {"E-1"},
    )
    high = aggregator.aggregate(
        "order",
        AgentAnalysis(summary="high", item_scores=[AgentItemScore(item_type="signal", score=4, is_direct_evidence=False, confidence=1.0, rationale="high", evidence_refs=["E-2"])]),
        {"signal": 1.0},
        {"E-2"},
    )
    assert combine_agent_scores([low, high]) == pytest.approx(0.8)


def test_direct_evidence_flag_is_valid_only_for_score_five() -> None:
    analysis = AgentAnalysis(
        summary="An invalid direct-evidence flag was returned.",
        item_scores=[
            AgentItemScore(
                item_type="transaction_activity",
                score=4,
                is_direct_evidence=True,
                confidence=1.0,
                rationale="Strong suspicion is not direct evidence.",
                evidence_refs=["TXN-1"],
            )
        ],
        direct_evidence_found=True,
    )

    result = AgentScoreAggregator().aggregate(
        "order",
        analysis,
        {"transaction_activity": 1.0},
        {"TXN-1"},
    )

    assert result.rejected_item_scores == 1
    assert result.score_aggregate is None


def test_item_score_rejects_non_integer_values() -> None:
    with pytest.raises(ValueError):
        AgentItemScore(
            item_type="transaction_activity",
            score=2.5,
            is_direct_evidence=False,
            confidence=1.0,
            rationale="Fractional scores are not part of the rubric.",
            evidence_refs=["TXN-1"],
        )
