from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.models import (
    GroundedBehaviorStep,
    GroundedObservedSignal,
    PatternSynthesisRequest,
    SemanticPatternDraft,
    SemanticSynthesisOutput,
)


LITERAL_CUE = "今天付款可以再便宜一半"


def investigation(
    case_id: str,
    verdict: str,
    evidence_id: str,
    text: str,
    *,
    confidence: float = 0.9,
) -> dict[str, Any]:
    impact = "supports_legitimate" if verdict == "normal" else "supports_fraud"
    stop_reason = "false_positive_evidence" if verdict == "normal" else "fraud_threshold"
    return {
        "case_id": case_id,
        "subject": {"type": "message", "id": evidence_id},
        "verdict": verdict,
        "confidence": confidence,
        "summary": "Evidence-grounded chat investigation result.",
        "findings": [
            {
                "type": "message_intent",
                "description": "The message intent was assessed from the cited text.",
                "impact": impact,
                "confidence": confidence,
                "evidence_refs": [evidence_id],
            }
        ],
        "evidence": [
            {
                "id": evidence_id,
                "source": "detection",
                "type": "message",
                "ref_id": f"conversation-{case_id}",
                "observed_at": "2026-09-12T01:00:00Z",
                "data": {
                    "text": text,
                    "sender_role": "seller",
                    "recipient_role": "buyer",
                },
            }
        ],
        "agents_invoked": [],
        "agent_results": [],
        "scoreboard": {
            "status": "stopped",
            "config_ref": {"version": "development-v1"},
            "scoring_policy_version": "specialist-weighted-v1",
            "fraud_score": confidence,
            "usage": {
                "agent_calls": 1,
                "tool_calls": 0,
                "investigation_steps": 1,
                "tokens": 100,
                "cost_usd": 0.0,
            },
            "budget": {
                "max_agent_calls": 3,
                "max_tool_calls": 8,
                "max_investigation_steps": 12,
                "max_tokens": 12000,
                "max_cost_usd": 1.0,
            },
            "agent_usage": [
                {
                    "agent_id": "chat",
                    "calls": 1,
                    "tool_calls": 0,
                    "tokens": 100,
                    "cost_usd": 0.0,
                }
            ],
            "stop_reason": stop_reason,
            "updated_at": "2026-09-12T01:01:00Z",
        },
        "stop_reason": stop_reason,
    }


def request_payload() -> dict[str, Any]:
    return {
        "synthesis_id": "SYN-conditional-discount-001",
        "candidate_results": [
            investigation(
                "CASE-FRAUD-001",
                "fraud",
                "EVID-MSG-001",
                f"{LITERAL_CUE}，請改用外部轉帳。",
            ),
            investigation(
                "CASE-SUSPICIOUS-002",
                "suspicious",
                "EVID-MSG-002",
                f"{LITERAL_CUE}，請離開賣場付款。",
                confidence=0.78,
            ),
        ],
        "counterexample_results": [
            investigation(
                "CASE-NORMAL-003",
                "normal",
                "EVID-MSG-003",
                "請只使用平台付款，不需要私下交易。",
                confidence=0.94,
            )
        ],
        "active_defense_version": {"version": "DV-007"},
        "active_policy_refs": [
            {"type": "detection", "version": "baseline-v1"},
            {"type": "investigation", "version": "development-v1"},
        ],
        "policy_capability_summary": {
            "summary": "Detection has flat phrase matching and independent anomaly checks.",
            "capabilities": [
                {
                    "capability_id": "detection-flat-chat-phrases",
                    "policy_type": "detection",
                    "kind": "CONFIG",
                    "surface": "rule_based.chat_request_phrases",
                    "description": "Exact substring matching over each message.",
                    "constraints": [
                        "flat phrase list",
                        "no sender/recipient role-aware conjunction",
                        "no semantic condition composition",
                    ],
                }
            ],
        },
        "pattern_hint": "conditional discount followed by off-platform redirection",
        "grouping_reason": "Analyst-selected cases share inducement language.",
    }


def synthesis_request() -> PatternSynthesisRequest:
    return PatternSynthesisRequest.model_validate(request_payload())


def reusable_pattern_output() -> SemanticSynthesisOutput:
    return SemanticSynthesisOutput(
        outcome="PATTERN",
        reason="Two suspicious cases share evidence-grounded conditional payment inducement.",
        pattern=SemanticPatternDraft(
            name="Conditional discount with off-platform payment redirection",
            description=(
                "A seller conditions a steep discount on immediate payment and redirects "
                "the buyer away from platform payment controls."
            ),
            observed_signals=(
                GroundedObservedSignal(
                    field="message.intent",
                    operator="eq",
                    value="conditional_payment_inducement",
                    description="Semantic intent shared across the grouped cases.",
                    grounding_kind="semantic",
                    evidence_refs=("EVID-MSG-001", "EVID-MSG-002"),
                ),
                GroundedObservedSignal(
                    field="message.text",
                    operator="contains",
                    value=LITERAL_CUE,
                    description="Evidence-grounded literal discount cue.",
                    grounding_kind="literal",
                    evidence_refs=("EVID-MSG-001", "EVID-MSG-002"),
                ),
            ),
            behavior_sequence=(
                GroundedBehaviorStep(
                    order=1,
                    action="offer_conditional_discount",
                    description="Offer a large discount contingent on immediate payment.",
                    evidence_refs=("EVID-MSG-001", "EVID-MSG-002"),
                ),
                GroundedBehaviorStep(
                    order=2,
                    action="redirect_payment_off_platform",
                    description="Direct the buyer away from marketplace payment controls.",
                    evidence_refs=("EVID-MSG-001", "EVID-MSG-002"),
                ),
            ),
            supporting_cases=("CASE-FRAUD-001", "CASE-SUSPICIOUS-002"),
            counterexamples=("CASE-NORMAL-003",),
            current_defense_gap=(
                "Active Detection exposes only flat exact-substring phrases at "
                "rule_based.chat_request_phrases; it cannot express the role-aware "
                "conjunction of conditional discount inducement and off-platform payment."
            ),
            defense_capability_refs=("detection-flat-chat-phrases",),
            evidence_refs=("EVID-MSG-001", "EVID-MSG-002"),
            confidence=0.88,
        ),
    )


class FakeSemanticSynthesizer:
    available = True

    def __init__(self, output: SemanticSynthesisOutput | None = None) -> None:
        self.output = output or reusable_pattern_output()
        self.contexts: list[dict[str, Any]] = []
        self.closed = False

    async def synthesize(self, context) -> SemanticSynthesisOutput:
        self.contexts.append(deepcopy(dict(context)))
        return self.output

    async def close(self) -> None:
        self.closed = True
