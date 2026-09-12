from __future__ import annotations

from typing import Mapping, Protocol, Any

from .domain import (
    BuildOutcome,
    CandidatePolicy,
    DefenseVersionSnapshot,
    DiagnosisResult,
    EvolutionContext,
    EvolutionRun,
    ImplementationDirective,
    PolicyChangeProposal,
)


class EvolutionPlanner(Protocol):
    """Reason about what is wrong and what behavior should change, never workflow state."""

    def diagnose(self, context: EvolutionContext) -> DiagnosisResult: ...

    def propose(
        self,
        run: EvolutionRun,
        context: EvolutionContext,
        diagnosis: DiagnosisResult,
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


class DefenseVersionRepository(Protocol):
    def get(self, version: str) -> DefenseVersionSnapshot: ...


class CandidateVersionFactory(Protocol):
    """Supply a provisional candidate version without fixing global numbering policy."""

    def create(
        self,
        run: EvolutionRun,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy,
        candidate_id: str,
    ) -> str: ...
