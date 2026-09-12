from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource

from app.domain.models import (
    CheckOutcome,
    GovernanceDecision,
    GovernancePolicyConfig,
    GovernanceRequest,
    HumanReviewInput,
    PolicyCheckResult,
)
from app.main import create_app
from app.service import GovernanceService


FIXED_TIME = datetime(2026, 9, 12, 3, 0, tzinfo=timezone.utc)


def evaluation(
    *,
    status: str = "passed",
    implementation_valid: bool = True,
    regressions: list[str] | None = None,
) -> dict:
    metrics = {
        "precision": 0.9,
        "recall": 0.8,
        "f1": 0.85,
        "false_positive_count": 2,
        "false_positive_rate": 0.02,
        "trigger_volume": 100,
    }
    return {
        "evaluation_id": "eval-001",
        "candidate_id": "candidate-001",
        "status": status,
        "implementation_valid": implementation_valid,
        "candidate_metrics": metrics,
        "baseline_metrics": metrics,
        "incremental_value": {"precision": 0.1},
        "regressions": regressions or [],
        "failure_reasons": [] if status == "passed" else ["threshold not met"],
    }


def request(**evaluation_overrides: object) -> GovernanceRequest:
    return GovernanceRequest.model_validate(
        {
            "candidate_id": "candidate-001",
            "evaluation": evaluation(**evaluation_overrides),
            "requested_by": "evolution-service",
            "require_human_approval": False,
        }
    )


def service(*, require_human_approval: bool = False) -> GovernanceService:
    ids = iter(f"event-{index}" for index in range(20))
    return GovernanceService(
        policy=GovernancePolicyConfig(
            require_human_approval=require_human_approval,
            block_reported_regressions=True,
        ),
        clock=lambda: FIXED_TIME,
        id_factory=lambda: next(ids),
    )


def record_human(governance: GovernanceService, decision: str) -> None:
    governance.record_human_decision(
        HumanReviewInput.model_validate(
            {
                "candidate_id": "candidate-001",
                "evaluation_id": "eval-001",
                "decision": decision,
                "reviewer": "reviewer-42",
                "reason": "Reviewed evaluation evidence.",
            }
        )
    )


def test_failed_evaluation_cannot_be_approved_even_after_human_approval() -> None:
    governance = service(require_human_approval=True)
    record_human(governance, "approve")

    result = governance.review(request(status="failed"))

    assert result.decision == GovernanceDecision.REJECT
    assert result.approved_defense_version is None


def test_invalid_implementation_cannot_be_approved() -> None:
    result = service().review(request(implementation_valid=False))

    assert result.decision == GovernanceDecision.REJECT
    assert "invalid" in result.reason


def test_required_human_approval_produces_needs_review() -> None:
    result = service(require_human_approval=True).review(request())

    assert result.decision == GovernanceDecision.NEEDS_REVIEW


def test_explicit_human_reject_produces_reject() -> None:
    governance = service(require_human_approval=True)
    record_human(governance, "reject")

    result = governance.review(request())

    assert result.decision == GovernanceDecision.REJECT
    assert "explicitly rejected" in result.reason


def test_explicit_human_approve_allows_approve_after_system_checks_pass() -> None:
    governance = service(require_human_approval=True)
    record_human(governance, "approve")

    result = governance.review(request())

    assert result.decision == GovernanceDecision.APPROVE
    assert "not executed" in result.reason


def test_candidate_input_cannot_override_trusted_governance_policy() -> None:
    payload = request().model_dump(mode="json")
    payload["governance_config"] = {"require_human_approval": False}

    with pytest.raises(ValidationError):
        GovernanceRequest.model_validate(payload)

    result = service(require_human_approval=True).review(request())
    assert result.decision == GovernanceDecision.NEEDS_REVIEW


def test_policy_checks_have_structured_names_pass_flags_and_reasons() -> None:
    result = service().review(request(regressions=["precision dropped"]))

    assert result.decision == GovernanceDecision.REJECT
    assert [check.name for check in result.policy_checks] == [
        "evaluation_passed",
        "implementation_valid",
        "no_blocking_regressions",
        "human_approval",
    ]
    assert all(isinstance(check.passed, bool) and check.reason for check in result.policy_checks)


def test_malformed_failed_extension_check_fails_closed() -> None:
    class IncompleteExternalCheck:
        def evaluate(self, context) -> CheckOutcome:
            del context
            return CheckOutcome(
                result=PolicyCheckResult(
                    name="external_compliance",
                    passed=False,
                    reason="Required compliance evidence is missing.",
                )
            )

    governance = GovernanceService(additional_checks=[IncompleteExternalCheck()])

    result = governance.review(request())

    assert result.decision == GovernanceDecision.REJECT
    assert "compliance evidence" in result.reason


def test_system_review_creates_an_audit_event() -> None:
    governance = service()

    governance.review(request())

    history = governance.audit_history("candidate-001")
    assert len(history) == 1
    assert history[0].event_type == "system_policy_decision"
    assert history[0].actor == "evolution-service"
    assert history[0].policy_checks


def test_human_and_system_decisions_are_distinct_and_append_only() -> None:
    governance = service(require_human_approval=True)
    governance.review(request())
    record_human(governance, "approve")
    governance.review(request())

    history = governance.audit_history("candidate-001")
    assert [event.event_type for event in history] == [
        "system_policy_decision",
        "human_review_decision",
        "system_policy_decision",
    ]
    assert history[1].human_reviewer == "reviewer-42"
    assert history[1].previous_decision == GovernanceDecision.NEEDS_REVIEW
    assert history[2].previous_decision == GovernanceDecision.APPROVE


def test_governance_never_modifies_or_returns_an_active_defense_version() -> None:
    active_version = {
        "version": "defense-v7",
        "status": "active",
        "policies": [{"type": "detection", "version": "policy-v7"}],
        "created_at": "2026-09-12T00:00:00Z",
    }
    original = deepcopy(active_version)

    result = service().review(request())

    assert active_version == original
    assert result.approved_defense_version is None


def test_result_is_compatible_with_unchanged_shared_governance_schema() -> None:
    result = service().review(request())
    schema_dir = Path(__file__).parents[3] / "shared" / "schemas"
    registry = Registry()
    for schema_path in schema_dir.glob("*.schema.json"):
        schema = json.loads(schema_path.read_text())
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema)
        )

    contract = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "governance.schema.json#/$defs/GovernanceResult",
    }
    Draft202012Validator(contract, registry=registry).validate(
        result.model_dump(mode="json")
    )


def test_http_adapter_uses_existing_review_contract_and_rejects_extras() -> None:
    with TestClient(create_app(service())) as client:
        response = client.post(
            "/governance/review", json=request().model_dump(mode="json")
        )
        invalid_payload = request().model_dump(mode="json")
        invalid_payload["policy"] = {"require_human_approval": False}
        invalid_response = client.post("/governance/review", json=invalid_payload)

    assert response.status_code == 200
    assert response.json()["decision"] == "approve"
    assert response.json()["approved_defense_version"] is None
    assert invalid_response.status_code == 422
