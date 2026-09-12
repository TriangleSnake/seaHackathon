from __future__ import annotations

from collections.abc import Mapping

from .domain import (
    ArtifactBoundary,
    CapabilityKind,
    DETECTION_CHAT_REQUEST_PHRASES_PATH,
    DETECTION_CODE_ALLOWED_PATHS,
    DETECTION_CODE_FORBIDDEN_PATHS,
    ImplementationDirective,
    PolicyChangeProposal,
    PolicyType,
)
from .ports import CandidateBuilder, PolicyCapabilityAdapter


class DetectionPolicyCapabilityAdapter:
    """Resolve the currently supported Detection policy CONFIG surface."""

    def resolve(self, proposal: PolicyChangeProposal) -> ImplementationDirective:
        if proposal.target_policy is not PolicyType.DETECTION:
            return ImplementationDirective(
                directive_id=f"unsupported:{proposal.proposal_id}",
                kind=CapabilityKind.UNSUPPORTED,
                target_policy=proposal.target_policy,
                summary="Detection capability adapter received another policy type",
                reason="This adapter only supports detection policy proposals",
            )
        if (
            not isinstance(proposal.base_policy_version, str)
            or not proposal.base_policy_version.strip()
        ):
            return ImplementationDirective(
                directive_id=f"unsupported:{proposal.proposal_id}",
                kind=CapabilityKind.UNSUPPORTED,
                target_policy=proposal.target_policy,
                summary="Detection baseline policy is unavailable",
                reason="A Detection CONFIG build requires a base policy version",
            )
        if not proposal.detection_policy_changes:
            return self._code_directive(
                proposal,
                summary="No structured Detection CONFIG change was proposed",
                reason="The requested behavior cannot be expressed as a CONFIG mutation",
            )
        if any(
            change.path != DETECTION_CHAT_REQUEST_PHRASES_PATH
            for change in proposal.detection_policy_changes
        ):
            return self._code_directive(
                proposal,
                summary="Detection change exceeds the supported CONFIG surface",
                reason="Only chat request phrase-list mutations are currently configurable",
            )
        if any(signal != "message.text" for signal in proposal.required_signals):
            return self._code_directive(
                proposal,
                summary="Detection behavior requires signals outside phrase CONFIG",
                reason=(
                    "Role-aware, account-aware, compound, or other multi-signal "
                    "behavior requires the CODE path"
                ),
            )
        return ImplementationDirective(
            directive_id=f"config:{proposal.proposal_id}",
            kind=CapabilityKind.CONFIG,
            target_policy=proposal.target_policy,
            summary="Apply validated Detection chat request phrase-list mutations",
            boundary=ArtifactBoundary(allowed_paths=("candidate/detection/",)),
            base_policy_version=proposal.base_policy_version,
            detection_policy_changes=tuple(
                change for change in proposal.detection_policy_changes
            ),
        )

    @staticmethod
    def _code_directive(
        proposal: PolicyChangeProposal, *, summary: str, reason: str
    ) -> ImplementationDirective:
        return ImplementationDirective(
            directive_id=f"code:{proposal.proposal_id}",
            kind=CapabilityKind.CODE,
            target_policy=proposal.target_policy,
            summary=summary,
            reason=reason,
            base_policy_version=proposal.base_policy_version,
            boundary=ArtifactBoundary(
                allowed_paths=DETECTION_CODE_ALLOWED_PATHS,
                forbidden_paths=DETECTION_CODE_FORBIDDEN_PATHS,
            ),
        )


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
            raise ValueError(
                "Capability adapter returned a directive for another policy"
            )
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
