from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .domain import (
    DefenseVersionSnapshot,
    DiagnosisOutcome,
    DiagnosisResult,
    EvolutionContext,
    PolicyChangeProposal,
    PolicyReference,
    PolicyType,
    TriggerType,
)


class ContractMappingError(ValueError):
    pass


class SharedContractAdapter:
    """Boundary between richer internal models and immutable shared JSON contracts."""

    def evolution_context(self, payload: Mapping[str, Any]) -> EvolutionContext:
        try:
            trigger = payload["trigger"]
            defense_ref = payload["current_defense_version"]
            performance = payload["system_performance"]
            trigger_type = TriggerType(trigger["type"])
            version = str(defense_ref["version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractMappingError("Invalid EvolutionRequest payload") from exc

        return EvolutionContext(
            trigger_type=trigger_type,
            trigger_context=deepcopy(trigger.get("context", {})),
            current_defense_version=version,
            system_performance=deepcopy(performance),
            pattern_spec=deepcopy(payload.get("pattern_spec")),
        )

    def evolution_result(
        self,
        context: EvolutionContext,
        diagnosis: DiagnosisResult,
        proposal: PolicyChangeProposal | None = None,
        reason_override: str | None = None,
    ) -> dict[str, Any]:
        if diagnosis.outcome is DiagnosisOutcome.CHANGE_NEEDED and proposal is not None:
            return {
                "action": "build_candidate",
                "reason": reason_override or diagnosis.reason,
                "pattern_spec": deepcopy(context.pattern_spec),
                "target_policies": [proposal.target_policy.value],
            }
        return {
            "action": "no_change",
            "reason": reason_override or diagnosis.reason,
            "pattern_spec": deepcopy(context.pattern_spec),
            "target_policies": [],
        }

    def build_request(
        self,
        build_id: str,
        context: EvolutionContext,
        proposal: PolicyChangeProposal,
    ) -> dict[str, Any]:
        if context.pattern_spec is None:
            raise ContractMappingError(
                "Shared BuildRequest requires pattern_spec; diagnosis needs more evidence"
            )
        return {
            "build_id": build_id,
            "pattern_spec": deepcopy(context.pattern_spec),
            "base_defense_version": {"version": proposal.base_defense_version},
            "target_policies": [proposal.target_policy.value],
            "config": {
                "objective": proposal.objective,
                "requested_behavior": proposal.requested_behavior,
                "required_signals": list(proposal.required_signals),
                "expected_impact": proposal.expected_impact,
                "known_risks": list(proposal.known_risks),
                "provenance": deepcopy(proposal.provenance),
            },
        }

    def defense_version(self, snapshot: DefenseVersionSnapshot) -> dict[str, Any]:
        return {
            "version": snapshot.version,
            "status": snapshot.status,
            "base_version": snapshot.base_version,
            "policies": [
                {"type": policy.policy_type.value, "version": policy.version}
                for policy in snapshot.policies
            ],
            "candidate_id": snapshot.candidate_id,
            "evaluation_id": snapshot.evaluation_id,
            "created_at": snapshot.created_at,
        }

    def defense_version_snapshot(
        self, payload: Mapping[str, Any]
    ) -> DefenseVersionSnapshot:
        try:
            return DefenseVersionSnapshot(
                version=str(payload["version"]),
                status=str(payload["status"]),
                base_version=payload.get("base_version"),
                policies=tuple(
                    PolicyReference(PolicyType(item["type"]), str(item["version"]))
                    for item in payload["policies"]
                ),
                candidate_id=payload.get("candidate_id"),
                evaluation_id=payload.get("evaluation_id"),
                created_at=str(payload["created_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractMappingError("Invalid DefenseVersion payload") from exc
