from __future__ import annotations

import json

from services.integration.demo_e2e import (
    build_evolution_request,
    build_synthesis_request,
    load_real_fixtures,
)


def _investigation(case_id: str, verdict: str, evidence_id: str) -> dict:
    stop_reason = "false_positive_evidence" if verdict == "normal" else "fraud_threshold"
    impact = "supports_legitimate" if verdict == "normal" else "supports_fraud"
    return {
        "case_id": case_id,
        "subject": {"type": "message", "id": evidence_id},
        "verdict": verdict,
        "confidence": 0.9,
        "summary": "Evidence-grounded integration fixture.",
        "findings": [
            {
                "type": "message_intent",
                "description": "The cited message was investigated.",
                "impact": impact,
                "confidence": 0.9,
                "evidence_refs": [evidence_id],
            }
        ],
        "evidence": [
            {
                "id": evidence_id,
                "source": "detection",
                "type": "message",
                "observed_at": "2026-09-12T01:00:00Z",
                "data": {"text": "請離開平台完成付款"},
            }
        ],
        "agents_invoked": [],
        "agent_results": [],
        "scoreboard": {
            "status": "stopped",
            "config_ref": {"version": "development-v1"},
            "scoring_policy_version": "specialist-weighted-v1",
            "fraud_score": 0.9,
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
            "agent_usage": [],
            "stop_reason": stop_reason,
            "updated_at": "2026-09-12T01:01:00Z",
        },
        "stop_reason": stop_reason,
    }


def test_build_synthesis_request_uses_real_contract_and_narrow_capability() -> None:
    payload = build_synthesis_request(
        [
            _investigation("CASE-1", "fraud", "EVID-1"),
            _investigation("CASE-2", "suspicious", "EVID-2"),
            _investigation("CASE-3", "normal", "EVID-3"),
        ],
        synthesis_id="SYN-DEMO-1",
        grouping_reason="test grouping",
        pattern_hint=None,
    )

    assert payload is not None
    assert [item["case_id"] for item in payload["candidate_results"]] == [
        "CASE-1",
        "CASE-2",
    ]
    assert [item["case_id"] for item in payload["counterexample_results"]] == [
        "CASE-3"
    ]
    capability = payload["policy_capability_summary"]["capabilities"][0]
    assert capability["surface"] == "rule_based.chat_request_phrases"
    assert "append_unique or remove only" in capability["constraints"]


def test_pattern_result_uses_shipped_evolution_handoff() -> None:
    request = build_synthesis_request(
        [
            _investigation("CASE-1", "fraud", "EVID-1"),
            _investigation("CASE-2", "suspicious", "EVID-2"),
        ],
        synthesis_id="SYN-DEMO-2",
        grouping_reason="test grouping",
        pattern_hint=None,
    )
    assert request is not None
    pattern = {
        "pattern_id": "PAT-DEMO-2",
        "name": "Off-platform payment request",
        "observed_signals": [
            {
                "field": "message.text",
                "operator": "contains",
                "value": "離開平台",
            }
        ],
        "supporting_cases": ["CASE-1", "CASE-2"],
        "counterexamples": [],
        "current_defense_gap": "Flat phrase rules miss this wording.",
        "evidence_refs": ["EVID-1", "EVID-2"],
        "confidence": 0.9,
    }
    result = {
        "status": "PATTERN",
        "reason": "Two cases share the behavior.",
        "pattern_spec": pattern,
        "provenance": {
            "synthesis_id": "SYN-DEMO-2",
            "candidate_case_ids": ["CASE-1", "CASE-2"],
            "counterexample_case_ids": [],
            "evidence_case_map": {"EVID-1": "CASE-1", "EVID-2": "CASE-2"},
            "active_defense_version": {"version": "DV-001"},
            "active_policy_refs": request["active_policy_refs"],
            "defense_capability_refs": ["detection-flat-chat-phrases"],
            "signal_grounding": [
                {
                    "signal_index": 0,
                    "grounding_kind": "semantic",
                    "evidence_refs": ["EVID-1", "EVID-2"],
                    "supporting_cases": ["CASE-1", "CASE-2"],
                }
            ],
            "behavior_grounding": [],
        },
    }

    evolution = build_evolution_request(request, result)

    assert evolution["trigger"]["context"]["source"] == "pattern_synthesis"
    assert evolution["pattern_spec"]["pattern_id"] == pattern["pattern_id"]
    assert evolution["pattern_spec"]["evidence_refs"] == pattern["evidence_refs"]
    assert evolution["current_defense_version"] == {"version": "DV-001"}


def test_real_fixture_loader_requires_no_payload_rewrite(tmp_path) -> None:
    fixture = _investigation("CASE-REAL", "suspicious", "EVID-REAL")
    path = tmp_path / "captured.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    assert load_real_fixtures([path]) == [fixture]


def test_no_suspicious_result_stops_before_pattern_api() -> None:
    assert (
        build_synthesis_request(
            [_investigation("CASE-NORMAL", "normal", "EVID-NORMAL")],
            synthesis_id="SYN-NO-PATTERN",
            grouping_reason="test grouping",
            pattern_hint=None,
        )
        is None
    )
