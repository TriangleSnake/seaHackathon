from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from services.evaluator.app.datasets import EvaluationDatasetReader
from services.evaluator.app.detection import DetectionDecision, DetectionPolicyEvaluator
from services.evaluator.app.gates import (
    StaticDetectionGateProvider,
    load_trusted_detection_gates,
)
from services.evaluator.app.models import (
    DatasetPhase,
    DatasetRef,
    DetectionCase,
    DetectionInput,
    EvaluationDataset,
    EvaluationPlan,
    PolicyType as EvaluatorPolicyType,
)
from services.evaluator.app.router import build_default_router
from services.evaluator.app.service import EvaluationService
from services.evolution.app.capabilities import BuilderRouter, CapabilityResolver
from services.evolution.app.domain import (
    ArtifactBoundary,
    BuildOutcome,
    CandidatePolicy,
    CapabilityKind,
    DefenseVersionSnapshot,
    DiagnosisOutcome,
    DiagnosisResult,
    EvolutionContext,
    EvolutionRun,
    GapSeverity,
    ImplementationDirective,
    PolicyChangeProposal,
    PolicyGap,
    PolicyReference,
    PolicyType,
)
from services.evolution.app.orchestrator import EvolutionOrchestrator
from services.evolution.app.versioning import VersionManager
from services.governance.app.domain.models import (
    GovernanceDecision,
    GovernancePolicyConfig,
    GovernanceRequest,
    HumanReviewInput,
)
from services.governance.app.service import GovernanceService


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = REPOSITORY_ROOT / "shared" / "schemas"
GATE_CONFIG = (
    REPOSITORY_ROOT
    / "services"
    / "evaluator"
    / "config"
    / "hackathon_detection_gates.json"
)
DATASET_REF = DatasetRef(
    DatasetPhase.VALIDATION, "fixture://member4/integrated-validation-v1"
)


class DeterministicPlanner:
    """TEST FAKE: always proposes one detection-policy change."""

    def diagnose(self, context: EvolutionContext) -> DiagnosisResult:
        del context
        return DiagnosisResult(
            outcome=DiagnosisOutcome.CHANGE_NEEDED,
            reason="Deterministic integration diagnosis",
            policy_gaps=(
                PolicyGap(
                    policy_type=PolicyType.DETECTION,
                    severity=GapSeverity.HIGH,
                    confidence=1.0,
                    symptom="Baseline produces an avoidable false positive",
                    hypothesized_cause="Test fixture baseline rule is too broad",
                    evidence_refs=("fixture://member4/evidence-1",),
                ),
            ),
            considered_policies=(PolicyType.DETECTION,),
            primary_gap_index=0,
        )

    def propose(
        self,
        run: EvolutionRun,
        context: EvolutionContext,
        diagnosis: DiagnosisResult,
    ) -> PolicyChangeProposal:
        del diagnosis
        return PolicyChangeProposal(
            proposal_id=f"proposal-{run.run_id}",
            target_policy=PolicyType.DETECTION,
            base_defense_version=context.current_defense_version,
            objective="Remove the fixture false positive",
            requested_behavior="Apply the deterministic fixture behavior",
            provenance={"source": "member4-integrated-smoke"},
        )


class DeterministicCapabilityAdapter:
    """TEST FAKE: reports a CONFIG build capability."""

    def resolve(self, proposal: PolicyChangeProposal) -> ImplementationDirective:
        return ImplementationDirective(
            directive_id=f"directive-{proposal.proposal_id}",
            kind=CapabilityKind.CONFIG,
            target_policy=proposal.target_policy,
            summary="Use the deterministic integration builder",
            boundary=ArtifactBoundary(allowed_paths=("candidate/detection/",)),
        )


class DeterministicCandidateBuilder:
    """TEST FAKE: returns a schema-shaped candidate without writing artifacts."""

    def __init__(self, policy_ref: str) -> None:
        self._policy_ref = policy_ref

    def build(
        self,
        build_request: Mapping[str, Any],
        proposal: PolicyChangeProposal,
        directive: ImplementationDirective,
    ) -> BuildOutcome:
        del directive
        candidate_id = f"candidate-{build_request['build_id']}"
        result = {
            "candidate_id": candidate_id,
            "build_id": build_request["build_id"],
            "base_defense_version": {"version": proposal.base_defense_version},
            "status": "built",
            "changes": [
                {
                    "target": "detection",
                    "operation": "modify",
                    "artifact_path": "candidate/detection/policy.json",
                    "summary": "Deterministic integration candidate",
                }
            ],
            "artifact_root": "candidate/",
            "build_log_ref": "fixture://member4/build-log",
        }
        return BuildOutcome(
            success=True,
            candidate_result=result,
            candidate_policy=CandidatePolicy(
                target_policy=PolicyType.DETECTION,
                policy_ref=PolicyReference(PolicyType.DETECTION, self._policy_ref),
                artifact_ref="candidate/detection/policy.json",
            ),
        )


class DeterministicDefenseRepository:
    """TEST FAKE: contains exactly one immutable baseline defense version."""

    def __init__(self) -> None:
        self._base = DefenseVersionSnapshot(
            version="defense-v1",
            status="active",
            policies=(
                PolicyReference(PolicyType.DETECTION, "detection/baseline-v1"),
            ),
            created_at="2026-09-12T00:00:00+00:00",
        )

    def get(self, version: str) -> DefenseVersionSnapshot:
        if version != self._base.version:
            raise KeyError(version)
        return self._base


class DeterministicCandidateVersionFactory:
    """TEST FAKE: supplies an explicit candidate-only version name."""

    def create(
        self,
        run: EvolutionRun,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy,
        candidate_id: str,
    ) -> str:
        del run, candidate_policy
        return f"fixture-{candidate_id}-from-{base.version}"


class DeterministicDatasetSource:
    """TEST FAKE: evaluator-only labelled dataset source."""

    def __init__(self) -> None:
        self._dataset = EvaluationDataset(DATASET_REF, _cases())

    def load(self, dataset_ref: DatasetRef) -> EvaluationDataset:
        if dataset_ref != DATASET_REF:
            raise KeyError(dataset_ref)
        return self._dataset


class DeterministicDetectionRunner:
    """TEST FAKE: executes named baseline/pass/fail fixture policies."""

    def run(self, policy_ref: str, case_input: DetectionInput) -> DetectionDecision:
        if policy_ref == "detection/baseline-v1":
            detected = case_input.case_id in {"fraud-1", "fraud-2", "normal-noisy"}
        elif policy_ref == "detection/candidate-pass":
            detected = case_input.case_id in {"fraud-1", "fraud-2"}
        elif policy_ref == "detection/candidate-fail":
            detected = True
        else:
            raise KeyError(policy_ref)
        return DetectionDecision(detected=detected, trigger_count=int(detected))


class DeterministicPlanResolver:
    """TEST FAKE: resolves candidate ids to evaluator-owned artifact refs."""

    def __init__(self, plans: Mapping[str, EvaluationPlan]) -> None:
        self._plans = dict(plans)

    def resolve(self, candidate_id: str, baseline_defense_version: str) -> EvaluationPlan:
        plan = self._plans[candidate_id]
        if baseline_defense_version != plan.baseline_defense_version:
            raise ValueError("Fixture baseline does not match")
        return plan


class Member4IntegratedSmokeTests(unittest.TestCase):
    def test_failed_evaluation_is_rejected_by_governance(self) -> None:
        artifacts = _run_flow("fail")

        self.assertEqual(artifacts["evaluation"]["status"], "failed")
        self.assertEqual(artifacts["governance"].decision, GovernanceDecision.REJECT)
        self.assertIsNone(artifacts["governance"].approved_defense_version)
        _validate_artifacts(artifacts)

    def test_passed_evaluation_requires_review_then_allows_explicit_approval(self) -> None:
        artifacts = _run_flow("pass")

        self.assertEqual(artifacts["evaluation"]["status"], "passed")
        self.assertEqual(artifacts["evaluation"]["regressions"], [])
        self.assertEqual(
            artifacts["governance"].decision, GovernanceDecision.NEEDS_REVIEW
        )

        governance_service = artifacts["governance_service"]
        governance_service.record_human_decision(
            HumanReviewInput.model_validate(
                {
                    "candidate_id": artifacts["candidate"]["candidate_id"],
                    "evaluation_id": artifacts["evaluation"]["evaluation_id"],
                    "decision": "approve",
                    "reviewer": "fixture-reviewer",
                    "reason": "Explicit approval in the integrated smoke test.",
                }
            )
        )
        approved = governance_service.review(artifacts["governance_request"])

        self.assertEqual(approved.decision, GovernanceDecision.APPROVE)
        self.assertIsNone(approved.approved_defense_version)
        artifacts["approved_governance"] = approved
        _validate_artifacts(artifacts)


def _run_flow(outcome: str) -> dict[str, Any]:
    policy_ref = f"detection/candidate-{outcome}"
    orchestrator = EvolutionOrchestrator(
        planner=DeterministicPlanner(),
        capability_resolver=CapabilityResolver(
            {PolicyType.DETECTION: DeterministicCapabilityAdapter()}
        ),
        builder_router=BuilderRouter(
            {CapabilityKind.CONFIG: DeterministicCandidateBuilder(policy_ref)}
        ),
        version_manager=VersionManager(DeterministicDefenseRepository()),
        candidate_version_factory=DeterministicCandidateVersionFactory(),
        id_factory=lambda prefix: f"{prefix}-{outcome}",
        timestamp_factory=lambda: "2026-09-12T01:00:00+00:00",
    )
    evolution = orchestrator.execute(_evolution_request())
    candidate = evolution.candidate_result
    candidate_version = evolution.candidate_defense_version
    assert candidate is not None and candidate_version is not None

    plan = EvaluationPlan(
        policy_type=EvaluatorPolicyType.DETECTION,
        baseline_defense_version="defense-v1",
        baseline_policy_ref="detection/baseline-v1",
        candidate_policy_ref=policy_ref,
    )
    evaluator = EvaluationService(
        router=build_default_router(
            DetectionPolicyEvaluator(
                DeterministicDetectionRunner(),
                StaticDetectionGateProvider(load_trusted_detection_gates(GATE_CONFIG)),
            )
        ),
        plan_resolver=DeterministicPlanResolver({candidate["candidate_id"]: plan}),
        datasets=EvaluationDatasetReader(DeterministicDatasetSource()),
    )
    evaluation = evaluator.evaluate(
        {
            "evaluation_id": f"evaluation-{outcome}",
            "candidate_id": candidate["candidate_id"],
            "baseline_defense_version": {"version": "defense-v1"},
            "datasets": [{"name": "validation", "ref": DATASET_REF.ref}],
        }
    )

    event_ids = iter(f"governance-event-{outcome}-{index}" for index in range(4))
    governance_service = GovernanceService(
        policy=GovernancePolicyConfig(
            require_human_approval=True,
            block_reported_regressions=True,
        ),
        id_factory=lambda: next(event_ids),
    )
    governance_request = GovernanceRequest.model_validate(
        {
            "candidate_id": candidate["candidate_id"],
            "evaluation": evaluation,
            "requested_by": "member4-integrated-smoke",
            "require_human_approval": True,
        }
    )
    governance = governance_service.review(governance_request)
    return {
        "evolution": evolution.evolution_result,
        "candidate": candidate,
        "candidate_version": candidate_version,
        "evaluation": evaluation,
        "governance": governance,
        "governance_request": governance_request,
        "governance_service": governance_service,
    }


def _evolution_request() -> dict[str, Any]:
    return {
        "trigger": {"type": "new_spec_ready", "context": {"source": "fixture"}},
        "current_defense_version": {"version": "defense-v1"},
        "system_performance": {"precision": 0.66},
        "pattern_spec": {
            "pattern_id": "pattern-member4-smoke",
            "name": "Member 4 smoke pattern",
            "description": "Deterministic integration-only pattern",
            "observed_signals": [
                {
                    "field": "account.fixture",
                    "operator": "eq",
                    "value": True,
                    "description": "Integration-only deterministic signal",
                }
            ],
            "current_defense_gap": "Baseline fixture produces one false positive",
            "confidence": 1.0,
            "evidence_refs": ["fixture://member4/evidence-1"],
        },
    }


def _cases() -> tuple[DetectionCase, ...]:
    def case(case_id: str, is_fraud: bool) -> DetectionCase:
        return DetectionCase(
            input=DetectionInput(
                case_id=case_id,
                subject_type="account",
                subject_id=f"account-{case_id}",
                facts={"fixture": True},
            ),
            is_fraud=is_fraud,
        )

    return (
        case("fraud-1", True),
        case("fraud-2", True),
        case("normal-noisy", False),
        case("normal-clean", False),
    )


def _validate_artifacts(artifacts: Mapping[str, Any]) -> None:
    registry = Registry()
    for schema_path in SCHEMA_ROOT.glob("*.schema.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema)
        )

    payloads = (
        ("evolution.schema.json#/$defs/EvolutionResult", artifacts["evolution"]),
        ("candidate.schema.json#/$defs/CandidateResult", artifacts["candidate"]),
        (
            "defense-version.schema.json#/$defs/DefenseVersion",
            artifacts["candidate_version"],
        ),
        ("evaluation.schema.json#/$defs/EvaluationResult", artifacts["evaluation"]),
        (
            "governance.schema.json#/$defs/GovernanceResult",
            artifacts["governance"].model_dump(mode="json"),
        ),
    )
    if "approved_governance" in artifacts:
        payloads += (
            (
                "governance.schema.json#/$defs/GovernanceResult",
                artifacts["approved_governance"].model_dump(mode="json"),
            ),
        )
    for ref, payload in payloads:
        Draft202012Validator(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$ref": ref,
            },
            registry=registry,
        ).validate(payload)


if __name__ == "__main__":
    unittest.main()
