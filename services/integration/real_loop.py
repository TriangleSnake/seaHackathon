"""One-shot real Member 4 CONFIG Evolution-loop demonstration.

This module composes the existing Evolution, ConfigBuilder, Evaluator,
Governance, and VersionManager components. It does not implement policy logic.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from services.detection.app.policies.repository import FilePolicyRepository
from services.evaluator.app.datasets import (
    EvaluationDatasetReader,
    HOLDOUT_DATASET_REF,
    ManifestDatasetSource,
    VALIDATION_DATASET_REF,
)
from services.evaluator.app.detection import (
    DetectionDecision,
    DetectionInput,
    DetectionPolicyEvaluator,
    HttpDetectionRunner,
)
from services.evaluator.app.environment import PostgresEnvironmentControl
from services.evaluator.app.gates import (
    StaticDetectionGateProvider,
    load_trusted_detection_gates,
)
from services.evaluator.app.plans import RegisteredCandidateEvaluationPlanResolver
from services.evaluator.app.router import build_default_router
from services.evaluator.app.service import EvaluationService
from services.evaluator.app.settings import DetectionHttpSettings
from services.evaluator.app.snapshots import EnvironmentSnapshotGuard
from services.evolution.app.capabilities import (
    BuilderRouter,
    CapabilityResolver,
    DetectionPolicyCapabilityAdapter,
)
from services.evolution.app.config_builder import ConfigBuilder, ConfigBuilderSettings
from services.evolution.app.code_builder import CodexCandidateBuilder
from services.evolution.app.domain import (
    CapabilityKind,
    ConfigListOperation,
    DETECTION_CHAT_REQUEST_PHRASES_PATH,
    DefenseVersionSnapshot,
    DetectionPolicyChange,
    DiagnosisOutcome,
    DiagnosisResult,
    EvolutionContext,
    EvolutionRun,
    GapSeverity,
    PolicyChangeProposal,
    PolicyGap,
    PolicyReference,
    PolicyType,
    RevisionFeedback,
    RunState,
)
from services.evolution.app.lifecycle import VersionLifecycle
from services.evolution.app.orchestrator import EvolutionOrchestrator
from services.evolution.app.planner import OpenAIEvolutionPlanner
from services.evolution.app.repositories import (
    InMemoryCandidatePolicyRegistry,
    InMemoryVersionRepository,
)
from services.evolution.app.runtime import DetectionConfigCapabilityProvider
from services.evolution.app.versioning import VersionManager
from services.governance.app.domain.models import (
    GovernanceDecision,
    GovernancePolicyConfig,
    GovernanceRequest,
    HumanReviewInput,
)
from services.governance.app.service import GovernanceService


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TARGET_TIME = datetime.fromisoformat("2026-09-10T12:00:00+08:00")
SCENARIO = "taiwan-marketplace-20260912"
GATE_CONFIG = REPOSITORY_ROOT / "services/evaluator/config/hackathon_detection_gates.json"
BASELINE_POLICY_DIR = REPOSITORY_ROOT / "services/detection/config/policies"
CANDIDATE_POLICY_DIR = REPOSITORY_ROOT / "runtime/detection-policies"
POLICY_SCHEMA = REPOSITORY_ROOT / "shared/schemas/detection-policy.schema.json"


class SequentialIds:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}-{self._counts[prefix]:03d}"


class CandidateDefenseVersionFactory:
    def create(self, run, base, candidate_policy, candidate_id) -> str:
        del base, candidate_policy, candidate_id
        return f"DV-CAND-{run.run_id}-{run.iteration:03d}"


class MechanicalPlanner:
    """Deterministic Phase 4 fixture; never used for the real Agent phase."""

    def diagnose(self, context: EvolutionContext) -> DiagnosisResult:
        del context
        return DiagnosisResult(
            outcome=DiagnosisOutcome.CHANGE_NEEDED,
            reason="Mechanical CONFIG pipeline proof",
            policy_gaps=(
                PolicyGap(
                    policy_type=PolicyType.DETECTION,
                    severity=GapSeverity.HIGH,
                    confidence=1.0,
                    symptom="Known validation message is missed",
                    hypothesized_cause="Broad payment wording is absent",
                    reasoning="Deterministic integration proof only",
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
        feedback: RevisionFeedback | None = None,
    ) -> PolicyChangeProposal:
        del diagnosis, feedback
        return PolicyChangeProposal(
            proposal_id=f"proposal-{run.run_id}-mechanical",
            target_policy=PolicyType.DETECTION,
            base_defense_version=context.current_defense_version,
            objective="Prove the real CONFIG candidate and evaluation path",
            requested_behavior="Add the broad phrase for deterministic validation",
            provenance={"fixture": "phase-4-mechanical-proof"},
            detection_policy_changes=(
                DetectionPolicyChange(
                    path=DETECTION_CHAT_REQUEST_PHRASES_PATH,
                    operation=ConfigListOperation.ADD,
                    values=("付款",),
                ),
            ),
        )


class RecordingDetectionRunner:
    def __init__(self, runner: HttpDetectionRunner) -> None:
        self._runner = runner
        self.decisions: dict[tuple[str, str], DetectionDecision] = {}
        self.call_count = 0

    def run(self, policy_ref: str, case_input: DetectionInput) -> DetectionDecision:
        decision = self._runner.run(policy_ref, case_input)
        self.call_count += 1
        self.decisions[(policy_ref, case_input.case_id)] = decision
        return decision


def load_runtime_env(path: Path) -> None:
    """Load only OpenAI model/key variables without logging their values."""

    if not path.is_file():
        raise FileNotFoundError(f"Runtime env file not found: {path}")
    allowed = {"OPENAI_API_KEY", "EVOLUTION_OPENAI_MODEL", "OPENAI_MODEL"}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def configured_model() -> str:
    return (
        os.environ.get("EVOLUTION_OPENAI_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "gpt-5-mini"
    )


def runtime_preflight(env_file: Path) -> bool:
    load_runtime_env(env_file)
    available = bool(os.environ.get("OPENAI_API_KEY"))
    print(f"Evolution runtime OPENAI_API_KEY available: {available}")
    print(f"Configured Evolution model: {configured_model()}")
    return available


def run_real_loop(
    env_file: Path,
    *,
    human_approve: bool,
    evolution_request: Mapping[str, Any] | None = None,
    code_builder_enabled: bool = False,
) -> dict[str, Any]:
    if not runtime_preflight(env_file):
        raise RuntimeError("OPENAI_API_KEY is unavailable to the Evolution runtime")

    database_url = os.environ.get(
        "MEMBER4_DATABASE_URL",
        "postgresql://fraud:fraud_dev_password@127.0.0.1:55432/fraud_intelligence",
    )
    environment = PostgresEnvironmentControl(database_url)
    verified = environment.verify_isolated(SCENARIO)
    _checkpoint("isolated_environment_verified", verified)
    current_time = datetime.fromisoformat(
        verified["simulation"]["simulation_time"]
    )
    if current_time == TARGET_TIME:
        overview_before = verified
        simulation_time_advanced = False
    else:
        overview_before = environment.set_simulation_time_once(TARGET_TIME)
        simulation_time_advanced = True
    _checkpoint(
        "environment_before_loop",
        {"overview": overview_before, "simulation_time_advanced": simulation_time_advanced},
    )

    registry = InMemoryCandidatePolicyRegistry()
    repository = InMemoryVersionRepository([_base_defense()])
    versions = VersionManager(repository, registry)
    ids = SequentialIds()
    builder = ConfigBuilder.from_settings(
        ConfigBuilderSettings(
            baseline_policy_dir=BASELINE_POLICY_DIR,
            candidate_policy_dir=CANDIDATE_POLICY_DIR,
            detection_policy_schema=POLICY_SCHEMA,
        ),
        registry,
    )
    resolver = CapabilityResolver(
        {PolicyType.DETECTION: DetectionPolicyCapabilityAdapter()}
    )
    builders = {CapabilityKind.CONFIG: builder}
    if code_builder_enabled:
        builders[CapabilityKind.CODE] = _build_codex_candidate_builder()
    router = BuilderRouter(builders)

    recording_runner = RecordingDetectionRunner(
        HttpDetectionRunner(
            ["rule_based"],
            settings=DetectionHttpSettings(
                base_url=os.environ.get(
                    "EVOLUTION_DETECTION_URL", "http://127.0.0.1:11001"
                ),
                timeout_seconds=float(
                    os.environ.get("DETECTION_TIMEOUT_SECONDS", "5")
                ),
            ),
        )
    )
    evaluator = EvaluationService(
        router=build_default_router(
            DetectionPolicyEvaluator(
                recording_runner,
                StaticDetectionGateProvider(
                    load_trusted_detection_gates(GATE_CONFIG)
                ),
            )
        ),
        plan_resolver=RegisteredCandidateEvaluationPlanResolver(versions),
        datasets=EvaluationDatasetReader(ManifestDatasetSource()),
        snapshot_guard=EnvironmentSnapshotGuard(environment),
    )

    mechanical = EvolutionOrchestrator(
        MechanicalPlanner(),
        resolver,
        router,
        versions,
        CandidateDefenseVersionFactory(),
        id_factory=ids,
    ).execute(_evolution_request({}), retry_budget=0)
    _require_candidate(mechanical, "mechanical")
    mechanical_policy = _candidate_policy_ref(mechanical)
    mechanical_hash = _artifact_hash(mechanical)
    _checkpoint(
        "mechanical_candidate",
        {
            "candidate_id": mechanical.candidate_result["candidate_id"],
            "policy_ref": mechanical_policy,
            "policy_diff": _proposal_diff(mechanical.proposal),
            "artifact_sha256": mechanical_hash,
        },
    )
    mechanical_evaluation = evaluator.evaluate(
        _evaluation_request(
            "evaluation-mechanical-validation",
            mechanical.candidate_result["candidate_id"],
            VALIDATION_DATASET_REF,
        )
    )
    _checkpoint(
        "mechanical_validation",
        {
            "result": mechanical_evaluation,
            "observed_changes": _observed_changes(
                recording_runner, "baseline-v1", mechanical_policy
            ),
        },
    )
    # VersionManager owns the durable candidate status for this proof.
    VersionLifecycle(versions).record_evaluation(
        mechanical.run,
        mechanical.candidate_defense_version["version"],
        mechanical_evaluation,
    )

    capability_provider = DetectionConfigCapabilityProvider(
        FilePolicyRepository(BASELINE_POLICY_DIR),
        versions,
        code_builder_available=code_builder_enabled,
    )
    planner = OpenAIEvolutionPlanner.from_env(
        capability_provider=capability_provider
    )
    real_orchestrator = EvolutionOrchestrator(
        planner,
        resolver,
        router,
        versions,
        CandidateDefenseVersionFactory(),
        id_factory=ids,
    )
    if evolution_request is None:
        request = _evolution_request(mechanical_evaluation["baseline_metrics"])
        pattern_source = "manual_member4_fixture"
    else:
        request = deepcopy(dict(evolution_request))
        request["system_performance"] = deepcopy(
            mechanical_evaluation["baseline_metrics"]
        )
        pattern_source = "pattern_synthesis_handoff"
    _validate_evolution_request(request)
    _checkpoint(
        "real_evolution_started",
        {
            "model": planner.model,
            "pattern_source": pattern_source,
        },
    )
    execution = real_orchestrator.execute(request, retry_budget=1)
    _checkpoint("diagnosis", _diagnosis_payload(execution.diagnosis))
    if execution.candidate_result is None:
        result = {
            "terminal_state": execution.run.current_state.value,
            "reason": execution.evolution_result.get("reason"),
            "openai_live_call_occurred": True,
            "detection_http_call_count": recording_runner.call_count,
            "resolver_mode": (
                execution.directive.kind.value if execution.directive else None
            ),
            "candidate_result": execution.candidate_result,
        }
        _checkpoint("real_evolution_terminal", result)
        return _finish(environment, overview_before, result)

    if execution.directive is not None and execution.directive.kind is CapabilityKind.CODE:
        metadata = _read_code_build_metadata(execution.candidate_result)
        code_passed = bool(
            execution.candidate_result.get("status") == "built"
            and metadata.get("test_status") == "passed"
            and metadata.get("status") == "built"
        )
        result = {
            "terminal_state": execution.run.current_state.value,
            "model": planner.model,
            "openai_live_call_occurred": True,
            "detection_http_call_count": recording_runner.call_count,
            "resolver_mode": "CODE",
            "candidate_result": execution.candidate_result,
            "code_build_validation": {
                "status": "passed" if code_passed else "failed",
                "candidate_commit": metadata.get("candidate_commit"),
                "changed_paths": metadata.get("changed_paths", []),
                "test_status": metadata.get("test_status", "not_run"),
                "failure_reason": metadata.get("failure_reason"),
                "metadata_ref": execution.candidate_result.get("build_log_ref"),
            },
            "validations": [],
            "holdout": None,
            "governance": None,
            "formal_version": None,
        }
        _checkpoint("code_build_validation", result["code_build_validation"])
        return _finish(environment, overview_before, result)

    if execution.candidate_defense_version is None:
        result = {
            "terminal_state": execution.run.current_state.value,
            "model": planner.model,
            "openai_live_call_occurred": True,
            "detection_http_call_count": recording_runner.call_count,
            "resolver_mode": (
                execution.directive.kind.value if execution.directive else None
            ),
            "candidate_result": execution.candidate_result,
            "validations": [],
            "holdout": None,
            "governance": None,
            "formal_version": None,
        }
        return _finish(environment, overview_before, result)

    validations: list[dict[str, Any]] = []
    first_artifact = Path(execution.candidate_result["changes"][0]["artifact_path"])
    first_hash = hashlib.sha256(first_artifact.read_bytes()).hexdigest()
    while execution.run.current_state is RunState.VALIDATING:
        candidate_id = execution.candidate_result["candidate_id"]
        iteration = execution.run.iteration
        policy_ref = _candidate_policy_ref(execution)
        _checkpoint(
            "candidate",
            {
                "iteration": iteration,
                "candidate_id": candidate_id,
                "policy_ref": policy_ref,
                "proposal": _proposal_payload(execution.proposal),
                "policy_diff": _proposal_diff(execution.proposal),
            },
        )
        evaluation = evaluator.evaluate(
            _evaluation_request(
                f"evaluation-real-validation-{iteration}",
                candidate_id,
                VALIDATION_DATASET_REF,
            )
        )
        validations.append(evaluation)
        _checkpoint(
            "validation",
            {"iteration": iteration, "policy_ref": policy_ref, "result": evaluation},
        )
        updated = real_orchestrator.handle_evaluation(execution, evaluation)
        if updated.run.current_state is RunState.VALIDATING:
            _checkpoint(
                "revision",
                {
                    "failed_candidate_id": candidate_id,
                    "feedback": _feedback_payload(updated.revision_feedback),
                    "next_iteration": updated.run.iteration,
                    "retry_budget_remaining": updated.run.retry_budget,
                },
            )
            execution = updated
            continue
        execution = updated
        break

    first_immutable = (
        first_artifact.is_file()
        and hashlib.sha256(first_artifact.read_bytes()).hexdigest() == first_hash
    )
    _checkpoint(
        "attempt_lineage",
        {
            "attempts": [_attempt_payload(item) for item in execution.run.attempts],
            "first_candidate_immutable": first_immutable,
            "retry_budget_remaining": execution.run.retry_budget,
        },
    )

    holdout: dict[str, Any] | None = None
    governance_payload: dict[str, Any] | None = None
    formal_version: dict[str, Any] | None = None
    if execution.run.current_state is RunState.FROZEN:
        VersionLifecycle(versions).begin_holdout(execution.run)
        holdout = evaluator.evaluate(
            _evaluation_request(
                "evaluation-real-holdout",
                execution.candidate_result["candidate_id"],
                HOLDOUT_DATASET_REF,
            )
        )
        _checkpoint("holdout", holdout)
        execution = real_orchestrator.handle_evaluation(execution, holdout)

        if execution.run.current_state is RunState.AWAITING_APPROVAL:
            governance = GovernanceService(
                policy=GovernancePolicyConfig(
                    require_human_approval=True,
                    block_reported_regressions=True,
                )
            )
            governance_request = GovernanceRequest.model_validate(
                {
                    "candidate_id": execution.candidate_result["candidate_id"],
                    "evaluation": holdout,
                    "requested_by": "member4-real-loop",
                    "require_human_approval": True,
                }
            )
            initial = governance.review(governance_request)
            governance_payload = initial.model_dump(mode="json")
            _checkpoint("governance_initial", governance_payload)
            lifecycle = VersionLifecycle(versions)
            lifecycle.apply_governance(
                execution.run,
                execution.candidate_defense_version["version"],
                holdout,
                initial,
            )
            if human_approve and initial.decision is GovernanceDecision.NEEDS_REVIEW:
                governance.record_human_decision(
                    HumanReviewInput.model_validate(
                        {
                            "candidate_id": execution.candidate_result["candidate_id"],
                            "evaluation_id": holdout["evaluation_id"],
                            "decision": "approve",
                            "reviewer": "hackathon-integration-request",
                            "reason": "Explicit approval requested for the one-shot integration demonstration.",
                        }
                    )
                )
                approved = governance.review(governance_request)
                governance_payload = approved.model_dump(mode="json")
                _checkpoint("governance_after_human_review", governance_payload)
                promoted = lifecycle.apply_governance(
                    execution.run,
                    execution.candidate_defense_version["version"],
                    holdout,
                    approved,
                )
                if promoted is not None:
                    activated = lifecycle.activate(execution.run, promoted.version)
                    formal_version = {
                        "promoted": asdict(promoted),
                        "activated": asdict(activated),
                    }
                    _checkpoint("formal_version", formal_version)

    summary = {
        "terminal_state": execution.run.current_state.value,
        "model": planner.model,
        "openai_live_call_occurred": True,
        "detection_http_call_count": recording_runner.call_count,
        "resolver_mode": "CONFIG",
        "candidate_result": execution.candidate_result,
        "mechanical": mechanical_evaluation,
        "validations": validations,
        "holdout": holdout,
        "governance": governance_payload,
        "formal_version": formal_version,
        "first_candidate_immutable": first_immutable,
        "revision_outcome": (
            "revised" if len(validations) > 1 else "not_needed"
        ),
    }
    return _finish(environment, overview_before, summary)


def _finish(
    environment: PostgresEnvironmentControl,
    before: Mapping[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    after = environment.get_environment_overview()
    unchanged = after == before
    _checkpoint("environment_after_loop", {"overview": after, "unchanged": unchanged})
    if not unchanged:
        raise RuntimeError("Environment snapshot changed during the real loop")
    _checkpoint("summary", summary)
    return summary


def _build_codex_candidate_builder() -> CodexCandidateBuilder:
    service_root = REPOSITORY_ROOT / "services" / "codex-builder"
    if str(service_root) not in sys.path:
        sys.path.insert(0, str(service_root))
    from codex_builder.container_runtime import DockerCodexCodeBuilder
    from codex_builder.runtime import CodeBuilderSettings

    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    settings = CodeBuilderSettings.for_detection(
        source_repository=REPOSITORY_ROOT,
        base_commit=head,
        acceptance_test=(
            service_root
            / "tests"
            / "acceptance"
            / "seller_conditional_payment_acceptance.py"
        ),
        candidate_root=os.environ.get(
            "CODEX_CANDIDATE_ROOT", "/private/tmp/demo-ready-codex-candidates"
        ),
        artifact_root=os.environ.get(
            "CODEX_ARTIFACT_ROOT", "/private/tmp/demo-ready-codex-artifacts"
        ),
    )
    engine = DockerCodexCodeBuilder(
        settings,
        image=os.environ.get(
            "CODEX_BUILDER_IMAGE", "member4-real-codex-builder:0.154.0"
        ),
    )
    return CodexCandidateBuilder(engine)


def _read_code_build_metadata(candidate_result: Mapping[str, Any]) -> dict[str, Any]:
    ref = candidate_result.get("build_log_ref")
    if not isinstance(ref, str) or not ref:
        return {}
    try:
        payload = json.loads(Path(ref).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _base_defense() -> DefenseVersionSnapshot:
    return DefenseVersionSnapshot(
        version="DV-001",
        status="active",
        policies=(
            PolicyReference(PolicyType.DETECTION, "baseline-v1"),
            PolicyReference(PolicyType.SCORING, "SP-001"),
            PolicyReference(PolicyType.EXPLORATION, "EP-001"),
            PolicyReference(PolicyType.INVESTIGATION, "IP-001"),
            PolicyReference(PolicyType.ASSOCIATION, "AP-001"),
        ),
        created_at="2026-09-12T00:00:00+08:00",
    )


def _evolution_request(system_performance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trigger": {
            "type": "new_spec_ready",
            "context": {
                "source": "manual_hackathon_fixture",
                "fixture_notice": "manual PatternSpec fixture for first real Evolution-loop demonstration",
            },
        },
        "current_defense_version": {"version": "DV-001"},
        "system_performance": dict(system_performance),
        "pattern_spec": {
            "pattern_id": "pattern-manual-message-off-platform-payment-v1",
            "name": "Manual off-platform payment request pattern",
            "description": "Manual PatternSpec fixture for first real Evolution-loop demonstration.",
            "observed_signals": [
                {
                    "field": "message.text",
                    "operator": "contains",
                    "value": "要求買家在平台外完成付款",
                    "description": "Fraud behavior asks a buyer to move payment outside marketplace protections.",
                }
            ],
            "current_defense_gap": "Current phrase rules miss a new off-platform payment request wording.",
            "confidence": 0.95,
            "evidence_refs": ["manual-fixture://member4/new-message-pattern"],
        },
    }


def _evaluation_request(evaluation_id: str, candidate_id: str, dataset_ref) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "candidate_id": candidate_id,
        "baseline_defense_version": {"version": "DV-001"},
        "datasets": [
            {"name": dataset_ref.phase.value, "ref": dataset_ref.ref}
        ],
    }


def _validate_evolution_request(payload: Mapping[str, Any]) -> None:
    registry = Registry()
    schema_root = REPOSITORY_ROOT / "shared/schemas"
    for schema_path in schema_root.glob("*.schema.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "evolution.schema.json#/$defs/EvolutionRequest",
        },
        registry=registry,
    ).validate(dict(payload))


def _require_candidate(execution, label: str) -> None:
    if execution.candidate_result is None or execution.candidate_defense_version is None:
        raise RuntimeError(f"{label} Evolution did not build a candidate")


def _candidate_policy_ref(execution) -> str:
    for reference in execution.candidate_defense_version["policies"]:
        if reference["type"] == "detection":
            return reference["version"]
    raise RuntimeError("Candidate defense has no Detection policy")


def _artifact_hash(execution) -> str:
    path = Path(execution.candidate_result["changes"][0]["artifact_path"])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observed_changes(
    runner: RecordingDetectionRunner, baseline_ref: str, candidate_ref: str
) -> dict[str, list[str]]:
    baseline = {
        case_id
        for (policy, case_id), decision in runner.decisions.items()
        if policy == baseline_ref and decision.detected
    }
    candidate = {
        case_id
        for (policy, case_id), decision in runner.decisions.items()
        if policy == candidate_ref and decision.detected
    }
    return {
        "newly_detected": sorted(candidate - baseline),
        "no_longer_detected": sorted(baseline - candidate),
    }


def _proposal_diff(proposal: PolicyChangeProposal | None) -> list[dict[str, Any]]:
    if proposal is None:
        return []
    return [
        {
            "path": change.path,
            "operation": change.operation.value,
            "values": list(change.values),
        }
        for change in proposal.detection_policy_changes
    ]


def _diagnosis_payload(diagnosis: DiagnosisResult) -> dict[str, Any]:
    return {
        "outcome": diagnosis.outcome.value,
        "reason": diagnosis.reason,
        "primary_gap": (
            {
                "policy_type": diagnosis.primary_gap.policy_type.value,
                "severity": diagnosis.primary_gap.severity.value,
                "confidence": diagnosis.primary_gap.confidence,
                "symptom": diagnosis.primary_gap.symptom,
                "hypothesized_cause": diagnosis.primary_gap.hypothesized_cause,
                "reasoning": diagnosis.primary_gap.reasoning,
            }
            if diagnosis.primary_gap
            else None
        ),
    }


def _proposal_payload(proposal: PolicyChangeProposal | None) -> Any:
    if proposal is None:
        return None
    intent = proposal.mutation_intent
    return {
        "proposal_id": proposal.proposal_id,
        "objective": proposal.objective,
        "requested_behavior": proposal.requested_behavior,
        "expected_impact": proposal.expected_impact,
        "known_risks": list(proposal.known_risks),
        "mutation_intent": (
            {
                "operation": intent.operation,
                "path": intent.path,
                "values": list(intent.values),
                "rationale": intent.rationale,
            }
            if intent
            else None
        ),
    }


def _feedback_payload(feedback: RevisionFeedback | None) -> Any:
    if feedback is None:
        return None
    return {
        "candidate_id": feedback.candidate_id,
        "evaluation_id": feedback.evaluation_id,
        "failure_reasons": list(feedback.failure_reasons),
        "regressions": list(feedback.regressions),
        "baseline_metrics": dict(feedback.baseline_metrics),
        "candidate_metrics": dict(feedback.candidate_metrics),
        "incremental_value": dict(feedback.incremental_value),
        "iteration": feedback.iteration,
    }


def _attempt_payload(attempt) -> dict[str, Any]:
    return {
        "iteration": attempt.iteration,
        "proposal_id": attempt.proposal.proposal_id,
        "candidate_id": attempt.candidate_id,
        "candidate_version": attempt.candidate_version,
        "evaluation_id": attempt.evaluation_id,
        "evaluation_status": attempt.evaluation_status,
        "holdout_evaluation_id": attempt.holdout_evaluation_id,
        "holdout_evaluation_status": attempt.holdout_evaluation_status,
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, (Mapping, MappingProxyType)):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _checkpoint(name: str, payload: Any) -> None:
    print(json.dumps({"checkpoint": name, "data": _json_safe(payload)}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "run"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--human-approve", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            return 0 if runtime_preflight(args.env_file) else 1
        run_real_loop(args.env_file, human_approve=args.human_approve)
        return 0
    except Exception as exc:
        secret = os.environ.get("OPENAI_API_KEY", "")
        message = str(exc)
        if secret:
            message = message.replace(secret, "[REDACTED]")
        _checkpoint(
            "fatal_error",
            {"type": type(exc).__name__, "message": message},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
