from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
import sys
from typing import Any, Protocol

from .adapters import SharedContractAdapter
from .domain import (
    BuildOutcome,
    CandidatePolicy,
    CapabilityKind,
    DETECTION_CODE_ALLOWED_PATHS,
    ImplementationDirective,
    PolicyChangeProposal,
    PolicyReference,
    PolicyType,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class CodeBuildEngine(Protocol):
    def build(self, **arguments: Any) -> Any: ...


class CodexCandidateBuilder:
    """Adapt the real code-builder runtime to the existing candidate lifecycle."""

    def __init__(
        self,
        engine: CodeBuildEngine,
        *,
        adapter: SharedContractAdapter | None = None,
    ) -> None:
        self._engine = engine
        self._adapter = adapter or SharedContractAdapter()

    @classmethod
    def from_runtime_settings(cls, settings: Any) -> "CodexCandidateBuilder":
        service_root = _REPOSITORY_ROOT / "services" / "codex-builder"
        if str(service_root) not in sys.path:
            sys.path.insert(0, str(service_root))
        from codex_builder.runtime import RealCodexCodeBuilder

        return cls(RealCodexCodeBuilder(settings))

    def build(
        self,
        build_request: Mapping[str, Any],
        proposal: PolicyChangeProposal,
        directive: ImplementationDirective,
    ) -> BuildOutcome:
        build_id = _required_string(build_request, "build_id")
        candidate_id = f"code-candidate-{_slug(build_id)}"
        try:
            self._validate_request(build_request, proposal, directive)
            built = self._engine.build(
                build_id=build_id,
                candidate_id=candidate_id,
                objective=proposal.objective,
                requested_behavior=proposal.requested_behavior,
                required_signals=proposal.required_signals,
                known_risks=proposal.known_risks,
                allowed_paths=directive.boundary.allowed_paths,
            )
            metadata = built.metadata
            if not built.success:
                result = self._candidate_result(
                    candidate_id,
                    build_id,
                    proposal,
                    status="failed",
                    artifact_root=metadata.candidate_workspace,
                    build_log_ref=built.metadata_path,
                )
                return BuildOutcome(
                    False,
                    result,
                    error=metadata.failure_reason or "Codex CODE candidate build failed",
                )
            if not metadata.candidate_commit:
                raise ValueError("Successful CODE build has no immutable candidate commit")
            artifact_ref = f"git:{metadata.candidate_commit}"
            result = self._candidate_result(
                candidate_id,
                build_id,
                proposal,
                status="built",
                artifact_root=metadata.candidate_workspace,
                build_log_ref=built.metadata_path,
                artifact_ref=artifact_ref,
                summary=(
                    f"Codex built Detection engine candidate {metadata.candidate_commit[:12]} "
                    f"with {len(metadata.changed_paths)} whitelisted file change(s)"
                ),
            )
            return BuildOutcome(
                True,
                result,
                CandidatePolicy(
                    target_policy=PolicyType.DETECTION,
                    policy_ref=PolicyReference(
                        PolicyType.DETECTION,
                        f"DP-CAND-CODE-{_slug(build_id)}",
                    ),
                    artifact_ref=artifact_ref,
                ),
            )
        except Exception as exc:
            result = self._candidate_result(
                candidate_id,
                build_id,
                proposal,
                status="failed",
            )
            return BuildOutcome(False, result, error=str(exc))

    def _candidate_result(
        self,
        candidate_id: str,
        build_id: str,
        proposal: PolicyChangeProposal,
        *,
        status: str,
        artifact_root: str | None = None,
        build_log_ref: str | None = None,
        artifact_ref: str | None = None,
        summary: str = "",
    ) -> dict[str, Any]:
        changes: tuple[Mapping[str, Any], ...] = ()
        if status == "built":
            changes = (
                {
                    "target": PolicyType.DETECTION.value,
                    "operation": "modify",
                    "artifact_path": artifact_ref,
                    "summary": summary,
                },
            )
        return self._adapter.candidate_result(
            candidate_id=candidate_id,
            build_id=build_id,
            base_defense_version=proposal.base_defense_version,
            status=status,
            changes=changes,
            artifact_root=artifact_root,
            build_log_ref=build_log_ref,
        )

    @staticmethod
    def _validate_request(
        build_request: Mapping[str, Any],
        proposal: PolicyChangeProposal,
        directive: ImplementationDirective,
    ) -> None:
        if proposal.target_policy is not PolicyType.DETECTION:
            raise ValueError("CodexCandidateBuilder currently supports Detection only")
        if directive.kind is not CapabilityKind.CODE:
            raise ValueError("CodexCandidateBuilder requires a CODE directive")
        if directive.target_policy is not proposal.target_policy:
            raise ValueError("CODE directive target does not match the proposal")
        if directive.boundary.allowed_paths != DETECTION_CODE_ALLOWED_PATHS:
            raise ValueError("CODE directive does not carry the exact Detection write boundary")
        if list(build_request.get("target_policies", ())) != [PolicyType.DETECTION.value]:
            raise ValueError("Detection CODE build must target exactly one policy")
        base = build_request.get("base_defense_version")
        if not isinstance(base, Mapping) or base.get("version") != proposal.base_defense_version:
            raise ValueError("BuildRequest base defense does not match the proposal")


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"BuildRequest {key} must be a non-empty string")
    return value


def _slug(value: str) -> str:
    slug = _SAFE_ID.sub("-", value).strip("-._")
    if not slug:
        raise ValueError("Build id has no safe candidate representation")
    return slug[:80]
