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
    RevisionFeedback,
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
        config: dict[str, Any] = {
            "objective": proposal.objective,
            "requested_behavior": proposal.requested_behavior,
            "required_signals": list(proposal.required_signals),
            "expected_impact": proposal.expected_impact,
            "known_risks": list(proposal.known_risks),
            "provenance": deepcopy(proposal.provenance),
        }
        if proposal.mutation_intent is not None:
            config["mutation_intent"] = {
                "operation": proposal.mutation_intent.operation,
                "path": proposal.mutation_intent.path,
                "values": list(proposal.mutation_intent.values),
                "rationale": proposal.mutation_intent.rationale,
            }
        return {
            "build_id": build_id,
            "pattern_spec": deepcopy(context.pattern_spec),
            "base_defense_version": {"version": proposal.base_defense_version},
            "target_policies": [proposal.target_policy.value],
            "config": config,
        }

    def revision_feedback(
        self,
        evaluation: Mapping[str, Any],
        previous_proposal: PolicyChangeProposal,
        *,
        iteration: int,
    ) -> RevisionFeedback:
        """Map only aggregate EvaluationResult fields into planner-visible data."""

        if evaluation.get("status") != "failed":
            raise ContractMappingError(
                "RevisionFeedback can only be created from a failed evaluation"
            )
        candidate_id = _non_empty_string(evaluation, "candidate_id")
        evaluation_id = _non_empty_string(evaluation, "evaluation_id")
        return RevisionFeedback(
            candidate_id=candidate_id,
            evaluation_id=evaluation_id,
            failure_reasons=_string_tuple(evaluation, "failure_reasons"),
            regressions=_string_tuple(evaluation, "regressions"),
            baseline_metrics=_aggregate_mapping(evaluation, "baseline_metrics"),
            candidate_metrics=_aggregate_mapping(evaluation, "candidate_metrics"),
            incremental_value=_aggregate_mapping(evaluation, "incremental_value"),
            iteration=iteration,
            previous_proposal=previous_proposal,
        )

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


def _non_empty_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ContractMappingError(f"EvaluationResult {key} must be a non-empty string")
    return value


def _string_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContractMappingError(f"EvaluationResult {key} must be a string array")
    return tuple(value)


def _aggregate_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, Mapping):
        raise ContractMappingError(f"EvaluationResult {key} must be an object")
    aggregate: dict[str, Any] = {}
    for metric, amount in value.items():
        if not isinstance(metric, str) or isinstance(amount, bool) or not isinstance(
            amount, (int, float, type(None))
        ):
            raise ContractMappingError(
                f"EvaluationResult {key} must contain only aggregate numeric values"
            )
        aggregate[metric] = deepcopy(amount)
    return aggregate
