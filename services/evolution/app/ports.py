from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol, Any

from .domain import (
    BuildOutcome,
    CandidatePolicy,
    CandidatePolicyRecord,
    DefenseVersionSnapshot,
    DiagnosisResult,
    EvolutionContext,
    EvolutionRun,
    ImplementationDirective,
    FormalPolicyVersion,
    PolicyChangeProposal,
    PolicyType,
    RevisionFeedback,
)


class EvolutionPlanner(Protocol):
    """Reason about what is wrong and what behavior should change, never workflow state."""

    def diagnose(self, context: EvolutionContext) -> DiagnosisResult: ...

    def propose(
        self,
        run: EvolutionRun,
        context: EvolutionContext,
        diagnosis: DiagnosisResult,
        feedback: RevisionFeedback | None = None,
    ) -> PolicyChangeProposal: ...


class PolicyCapabilityAdapter(Protocol):
    """Resolve one policy proposal to CONFIG, CODE, or UNSUPPORTED."""

    def resolve(self, proposal: PolicyChangeProposal) -> ImplementationDirective: ...


class CandidateBuilder(Protocol):
    """Build only in a candidate workspace and return the shared CandidateResult shape."""

    def build(
        self,
        build_request: Mapping[str, Any],
        proposal: PolicyChangeProposal,
        directive: ImplementationDirective,
    ) -> BuildOutcome: ...


class ArtifactPublisher(Protocol):
    @property
    def root(self) -> Path: ...

    def publish(self, version: str, artifact: Mapping[str, Any]) -> str: ...


class DefenseVersionRepository(Protocol):
    def get(self, version: str) -> DefenseVersionSnapshot: ...

    def save_candidate(self, snapshot: DefenseVersionSnapshot) -> None: ...

    def link_evaluation(
        self, version: str, evaluation_id: str, *, rejected: bool
    ) -> DefenseVersionSnapshot: ...

    def reject_candidate(self, version: str) -> DefenseVersionSnapshot: ...

    def next_policy_version(self, policy_type: PolicyType) -> str: ...

    def next_defense_version(self) -> str: ...

    def save_promotion(
        self,
        policy: FormalPolicyVersion,
        defense: DefenseVersionSnapshot,
    ) -> None: ...

    def activate(self, version: str) -> DefenseVersionSnapshot: ...


class CandidatePolicyRegistry(Protocol):
    def allocate_candidate_policy_version(self, policy_type: PolicyType) -> str: ...

    def has_build(self, build_id: str) -> bool: ...

    def register(
        self,
        candidate_result: Mapping[str, Any],
        target_policy: PolicyType,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy | None,
    ) -> CandidatePolicyRecord: ...

    def get(self, candidate_id: str) -> CandidatePolicyRecord: ...

    def resolve(self, candidate_id: str) -> CandidatePolicy: ...


class CandidateVersionFactory(Protocol):
    """Supply a provisional candidate version without fixing global numbering policy."""

    def create(
        self,
        run: EvolutionRun,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy,
        candidate_id: str,
    ) -> str: ...
