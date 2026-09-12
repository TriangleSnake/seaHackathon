from __future__ import annotations

from collections.abc import Mapping

from .domain import (
    CapabilityKind,
    ImplementationDirective,
    PolicyChangeProposal,
    PolicyType,
)
from .ports import CandidateBuilder, PolicyCapabilityAdapter


class CapabilityResolver:
    """Shared Evolution Core registry for policy-specific capability adapters."""

    def __init__(self, adapters: Mapping[PolicyType, PolicyCapabilityAdapter]) -> None:
        self._adapters = dict(adapters)

    def resolve(self, proposal: PolicyChangeProposal) -> ImplementationDirective:
        adapter = self._adapters.get(proposal.target_policy)
        if adapter is None:
            return ImplementationDirective(
                directive_id=f"unsupported:{proposal.proposal_id}",
                kind=CapabilityKind.UNSUPPORTED,
                target_policy=proposal.target_policy,
                summary="No capability adapter is registered for this policy type",
                reason="Required runtime capability is unavailable",
            )
        directive = adapter.resolve(proposal)
        if directive.target_policy is not proposal.target_policy:
            raise ValueError("Capability adapter returned a directive for another policy")
        return directive


class BuilderRouter:
    """Route CONFIG and CODE directives into one common candidate flow."""

    def __init__(self, builders: Mapping[CapabilityKind, CandidateBuilder]) -> None:
        self._builders = dict(builders)

    def builder_for(self, directive: ImplementationDirective) -> CandidateBuilder:
        if directive.kind is CapabilityKind.UNSUPPORTED:
            raise ValueError("UNSUPPORTED directives cannot be built")
        try:
            return self._builders[directive.kind]
        except KeyError as exc:
            raise LookupError(
                f"No builder registered for {directive.kind.value} directives"
            ) from exc
