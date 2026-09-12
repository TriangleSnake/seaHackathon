from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import ContractError
from .models import DatasetPhase, DatasetRef, EvaluationRequest, PolicyEvaluationOutcome


_REQUEST_KEYS = {
    "evaluation_id",
    "candidate_id",
    "baseline_defense_version",
    "datasets",
    "thresholds",
}


def parse_evaluation_request(payload: Mapping[str, Any]) -> EvaluationRequest:
    unknown = set(payload) - _REQUEST_KEYS
    if unknown:
        raise ContractError(f"Unexpected EvaluationRequest fields: {sorted(unknown)}")

    try:
        evaluation_id = _non_empty_string(payload["evaluation_id"], "evaluation_id")
        candidate_id = _non_empty_string(payload["candidate_id"], "candidate_id")
        baseline = payload["baseline_defense_version"]
        datasets_payload = payload["datasets"]
    except KeyError as exc:
        raise ContractError(f"Missing EvaluationRequest field: {exc.args[0]}") from exc

    if not isinstance(baseline, Mapping) or set(baseline) != {"version"}:
        raise ContractError("baseline_defense_version must contain only version")
    baseline_version = _non_empty_string(baseline["version"], "baseline version")

    if not isinstance(datasets_payload, list) or not datasets_payload:
        raise ContractError("datasets must be a non-empty array")

    datasets: list[DatasetRef] = []
    for index, item in enumerate(datasets_payload):
        if not isinstance(item, Mapping) or set(item) != {"name", "ref"}:
            raise ContractError(f"datasets[{index}] must contain only name and ref")
        try:
            phase = DatasetPhase(item["name"])
        except (TypeError, ValueError) as exc:
            raise ContractError(f"datasets[{index}].name is not a supported phase") from exc
        datasets.append(
            DatasetRef(phase=phase, ref=_non_empty_string(item["ref"], f"datasets[{index}].ref"))
        )

    requested_thresholds = payload.get("thresholds", {})
    if not isinstance(requested_thresholds, Mapping):
        raise ContractError("thresholds must be an object when supplied")

    return EvaluationRequest(
        evaluation_id=evaluation_id,
        candidate_id=candidate_id,
        baseline_defense_version=baseline_version,
        datasets=tuple(datasets),
        requested_thresholds=requested_thresholds,
    )


def render_evaluation_result(
    request: EvaluationRequest, outcome: PolicyEvaluationOutcome
) -> dict[str, Any]:
    """Adapt flexible internal output to the existing detection-oriented schema."""

    return {
        "evaluation_id": request.evaluation_id,
        "candidate_id": request.candidate_id,
        "status": "passed" if outcome.passed else "failed",
        "implementation_valid": outcome.implementation_valid,
        "candidate_metrics": _render_shared_metrics(outcome.candidate_metrics),
        "baseline_metrics": _render_shared_metrics(outcome.baseline_metrics),
        "incremental_value": dict(outcome.incremental_value),
        "regressions": list(outcome.regressions),
        "failure_reasons": list(outcome.failure_reasons),
    }


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field_name} must be a non-empty string")
    return value


def _render_shared_metrics(
    metrics: Mapping[str, int | float | None],
) -> dict[str, int | float | None]:
    ordered_fields = (
        "precision",
        "recall",
        "f1",
        "false_positive_count",
        "false_positive_rate",
        "trigger_volume",
    )
    missing = set(ordered_fields) - set(metrics)
    if missing:
        raise ContractError(
            "Policy metrics cannot be represented by the current shared schema; "
            f"missing fields: {sorted(missing)}"
        )
    return {name: metrics[name] for name in ordered_fields}
