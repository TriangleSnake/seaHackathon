from dataclasses import dataclass

from app.code_builder import CodexCandidateBuilder
from app.capabilities import BuilderRouter, CapabilityResolver, DetectionPolicyCapabilityAdapter
from app.domain import (
    BuildOutcome,
    CapabilityKind,
    DefenseVersionSnapshot,
    DiagnosisOutcome,
    DiagnosisResult,
    GapSeverity,
    PolicyGap,
    PolicyChangeProposal,
    PolicyReference,
    PolicyType,
    RunState,
)
from app.orchestrator import EvolutionOrchestrator
from app.repositories import InMemoryCandidatePolicyRegistry, InMemoryVersionRepository
from app.versioning import VersionManager


@dataclass(frozen=True)
class Metadata:
    candidate_workspace: str = "/tmp/code-candidate"
    candidate_commit: str | None = "a" * 40
    changed_paths: tuple[str, ...] = (
        "services/detection/app/repository.py",
        "services/detection/app/detectors/rules.py",
    )
    failure_reason: str | None = None


@dataclass(frozen=True)
class EngineResult:
    success: bool
    metadata: Metadata
    metadata_path: str = "/tmp/code-candidate.json"


class Engine:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.calls = []

    def build(self, **arguments):
        self.calls.append(arguments)
        metadata = Metadata(
            candidate_commit="a" * 40 if self.success else None,
            failure_reason=None if self.success else "authoritative tests failed",
        )
        return EngineResult(self.success, metadata)


def proposal() -> PolicyChangeProposal:
    return PolicyChangeProposal(
        proposal_id="proposal-seller-payment-inducement",
        target_policy=PolicyType.DETECTION,
        base_defense_version="DV-001",
        base_policy_version="baseline-v1",
        objective="Detect seller conditional-payment inducement",
        requested_behavior=(
            "Trigger seller messages only when payment action and extreme discount "
            "or urgency inducement occur together"
        ),
        required_signals=(
            "sender.marketplace_role",
            "message.payment_action",
            "message.inducement",
        ),
        known_risks=("legitimate seller promotion language",),
        provenance={"source": "test"},
    )


def request() -> dict:
    return {
        "build_id": "build-hero-code",
        "pattern_spec": {"pattern_id": "pattern-hero-code"},
        "base_defense_version": {"version": "DV-001"},
        "target_policies": ["detection"],
    }


def test_code_builder_reuses_candidate_result_and_internal_candidate_namespace() -> None:
    candidate_proposal = proposal()
    directive = DetectionPolicyCapabilityAdapter().resolve(candidate_proposal)
    engine = Engine()

    outcome = CodexCandidateBuilder(engine).build(request(), candidate_proposal, directive)

    assert isinstance(outcome, BuildOutcome)
    assert outcome.success is True
    assert outcome.candidate_result["candidate_id"] == "code-candidate-build-hero-code"
    assert outcome.candidate_result["status"] == "built"
    assert outcome.candidate_result["build_log_ref"] == "/tmp/code-candidate.json"
    assert outcome.candidate_policy is not None
    assert outcome.candidate_policy.policy_ref.version == "DP-CAND-CODE-build-hero-code"
    assert outcome.candidate_policy.artifact_ref == f"git:{'a' * 40}"
    assert engine.calls[0]["allowed_paths"] == directive.boundary.allowed_paths


def test_failed_code_build_has_no_candidate_policy_or_production_identity() -> None:
    candidate_proposal = proposal()
    directive = DetectionPolicyCapabilityAdapter().resolve(candidate_proposal)

    outcome = CodexCandidateBuilder(Engine(False)).build(
        request(), candidate_proposal, directive
    )

    assert outcome.success is False
    assert outcome.candidate_result["status"] == "failed"
    assert outcome.candidate_result["changes"] == []
    assert outcome.candidate_policy is None
    assert outcome.error == "authoritative tests failed"


def test_role_aware_conjunctive_proposal_routes_to_code() -> None:
    directive = DetectionPolicyCapabilityAdapter().resolve(proposal())

    assert directive.kind.value == "CODE"
    assert directive.detection_policy_changes == ()


class Planner:
    def diagnose(self, context):
        del context
        return DiagnosisResult(
            outcome=DiagnosisOutcome.CHANGE_NEEDED,
            reason="Seller conditional-payment behavior is missed",
            policy_gaps=(
                PolicyGap(
                    policy_type=PolicyType.DETECTION,
                    severity=GapSeverity.HIGH,
                    confidence=1.0,
                    symptom="Seller payment inducement was not detected",
                    hypothesized_cause="Detection lacks role-aware conjunction",
                ),
            ),
            considered_policies=(PolicyType.DETECTION,),
            primary_gap_index=0,
        )

    def propose(self, run, context, diagnosis, feedback=None):
        del run, context, diagnosis, feedback
        return proposal()


class CandidateVersionFactory:
    def create(self, run, base, candidate_policy, candidate_id):
        del run, base, candidate_policy, candidate_id
        return "DV-CAND-CODE-001"


class ConfigBuilderMustNotRun:
    def build(self, *args, **kwargs):
        raise AssertionError("Role-aware conjunctive behavior reached ConfigBuilder")


def test_deterministic_evolution_pipeline_selects_code_builder_not_config() -> None:
    registry = InMemoryCandidatePolicyRegistry()
    versions = InMemoryVersionRepository(
        [
            DefenseVersionSnapshot(
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
        ]
    )
    engine = Engine()
    code_builder = CodexCandidateBuilder(engine)
    orchestrator = EvolutionOrchestrator(
        planner=Planner(),
        capability_resolver=CapabilityResolver(
            {PolicyType.DETECTION: DetectionPolicyCapabilityAdapter()}
        ),
        builder_router=BuilderRouter(
            {
                CapabilityKind.CONFIG: ConfigBuilderMustNotRun(),
                CapabilityKind.CODE: code_builder,
            }
        ),
        version_manager=VersionManager(versions, registry),
        candidate_version_factory=CandidateVersionFactory(),
        id_factory=lambda prefix: f"{prefix}-hero-code",
        timestamp_factory=lambda: "2026-09-12T12:00:00+08:00",
    )

    execution = orchestrator.execute(
        {
            "trigger": {"type": "new_spec_ready", "context": {"source": "test"}},
            "current_defense_version": {"version": "DV-001"},
            "system_performance": {"recall": 0.5},
            "pattern_spec": {
                "pattern_id": "pattern-hero-code",
                "name": "Seller conditional payment inducement",
                "description": "Seller combines payment action and extreme discount",
                "observed_signals": [],
                "current_defense_gap": "No role-aware conjunction",
                "confidence": 1.0,
                "evidence_refs": [],
            },
        }
    )

    assert execution.directive is not None
    assert execution.directive.kind is CapabilityKind.CODE
    assert execution.run.current_state is RunState.VALIDATING
    assert execution.candidate_result is not None
    assert execution.candidate_result["candidate_id"] == "code-candidate-build-hero-code"
    assert engine.calls
    record = registry.get("code-candidate-build-hero-code")
    assert record.candidate_policy_version == "DP-CAND-CODE-build-hero-code"
