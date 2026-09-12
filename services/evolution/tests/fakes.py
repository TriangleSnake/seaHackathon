from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain import (
    ArtifactBoundary,
    BuildOutcome,
    CandidatePolicy,
    CapabilityKind,
    DefenseVersionSnapshot,
    DiagnosisResult,
    EvolutionContext,
    EvolutionRun,
    ImplementationDirective,
    PolicyChangeProposal,
    PolicyReference,
    RevisionFeedback,
)
from app.repositories import InMemoryVersionRepository


class FakeEvolutionPlanner:
    """Deterministic test double; it contains no fraud or LLM reasoning."""

    def __init__(self, diagnosis: DiagnosisResult) -> None:
        self.diagnosis = diagnosis
        self.proposal_calls = 0
        self.feedback_calls: list[RevisionFeedback | None] = []

    def diagnose(self, context: EvolutionContext) -> DiagnosisResult:
        return self.diagnosis

    def propose(
        self,
        run: EvolutionRun,
        context: EvolutionContext,
        diagnosis: DiagnosisResult,
        feedback: RevisionFeedback | None = None,
    ) -> PolicyChangeProposal:
        self.proposal_calls += 1
        self.feedback_calls.append(feedback)
        gap = diagnosis.primary_gap
        if gap is None:
            raise ValueError("Fake planner cannot propose without a primary gap")
        return PolicyChangeProposal(
            proposal_id=f"proposal-{run.run_id}-{self.proposal_calls}",
            target_policy=gap.policy_type,
            base_defense_version=context.current_defense_version,
            objective=f"Address: {gap.symptom}",
            requested_behavior=(
                "Revise the requested test behavior from aggregate evaluation feedback"
                if feedback is not None
                else "Apply the requested test behavior"
            ),
            required_signals=("account.activity_score",),
            expected_impact="Improve detection coverage",
            known_risks=("False positives",),
            provenance={"run_id": run.run_id, "evidence_refs": gap.evidence_refs},
        )


class FakePolicyCapabilityAdapter:
    """Return a configured capability kind without inspecting runtime systems."""

    def __init__(self, kind: CapabilityKind) -> None:
        self.kind = kind

    def resolve(self, proposal: PolicyChangeProposal) -> ImplementationDirective:
        return ImplementationDirective(
            directive_id=f"directive-{proposal.proposal_id}",
            kind=self.kind,
            target_policy=proposal.target_policy,
            summary="Deterministic fake capability resolution",
            boundary=ArtifactBoundary(
                allowed_paths=(f"candidate/{proposal.target_policy.value}/",)
            ),
            reason=(
                "Test adapter reports unsupported"
                if self.kind is CapabilityKind.UNSUPPORTED
                else ""
            ),
        )


class FakeCandidateBuilder:
    """Create a schema-shaped result without writing files or invoking Codex."""

    def __init__(self, *, succeeds: bool, policy_version: str = "candidate-policy") -> None:
        self.succeeds = succeeds
        self.policy_version = policy_version
        self.calls: list[Mapping[str, Any]] = []

    def build(
        self,
        build_request: Mapping[str, Any],
        proposal: PolicyChangeProposal,
        directive: ImplementationDirective,
    ) -> BuildOutcome:
        self.calls.append(build_request)
        candidate_id = f"candidate-{build_request['build_id']}"
        result = {
            "candidate_id": candidate_id,
            "build_id": build_request["build_id"],
            "base_defense_version": {
                "version": proposal.base_defense_version
            },
            "status": "built" if self.succeeds else "failed",
            "changes": (
                [
                    {
                        "target": proposal.target_policy.value,
                        "operation": "modify",
                        "artifact_path": (
                            f"candidate/{proposal.target_policy.value}/policy.json"
                        ),
                        "summary": "Fake candidate change",
                    }
                ]
                if self.succeeds
                else []
            ),
            "artifact_root": "candidate/" if self.succeeds else None,
            "build_log_ref": "build-log:test",
        }
        if not self.succeeds:
            return BuildOutcome(False, result, error="Fake builder failure")
        policy = CandidatePolicy(
            target_policy=proposal.target_policy,
            policy_ref=PolicyReference(proposal.target_policy, self.policy_version),
            artifact_ref=f"candidate/{proposal.target_policy.value}/policy.json",
        )
        return BuildOutcome(True, result, candidate_policy=policy)


class FakeDefenseVersionRepository(InMemoryVersionRepository):
    def __init__(self, versions: list[DefenseVersionSnapshot]) -> None:
        super().__init__(versions)


class FakeCandidateVersionFactory:
    """Explicit test-only naming; production numbering remains undecided."""

    def create(
        self,
        run: EvolutionRun,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy,
        candidate_id: str,
    ) -> str:
        return f"test-candidate-{run.iteration}-for-{candidate_id}"
