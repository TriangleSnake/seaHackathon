from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import BaselineExecutionError, DatasetAccessError
from .gates import DetectionGateConfig, DetectionGateProvider
from .models import (
    DetectionCase,
    DetectionInput,
    EvaluationJob,
    PolicyEvaluationOutcome,
    PolicyType,
)


@dataclass(frozen=True)
class DetectionDecision:
    detected: bool
    trigger_count: int

    def __post_init__(self) -> None:
        if self.trigger_count < 0:
            raise ValueError("trigger_count cannot be negative")
        if not self.detected and self.trigger_count:
            raise ValueError("an undetected decision cannot contain triggers")


class DetectionRunner(Protocol):
    """Executes one immutable policy artifact against label-free case input."""

    def run(self, policy_ref: str, case_input: DetectionInput) -> DetectionDecision: ...


class ContractDetectionRunner:
    """Adapter for a future Detection runtime using the shared Detection contracts.

    The executor owns artifact loading and runtime transport. The adapter passes only
    the schema-defined subject request and translates the returned DetectionResult;
    it never implements detection logic itself.
    """

    def __init__(
        self,
        executor: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
    ) -> None:
        self._executor = executor

    def run(self, policy_ref: str, case_input: DetectionInput) -> DetectionDecision:
        request = {
            "subject": {
                "type": case_input.subject_type,
                "id": case_input.subject_id,
            },
            "trigger_context": {"source": "scheduled", "reason": "evaluation"},
        }
        result = self._executor(policy_ref, request)
        detected = result.get("detected")
        triggers = result.get("triggers")
        if not isinstance(detected, bool) or not isinstance(triggers, list):
            raise ValueError("Detection runtime returned an invalid DetectionResult")
        # A positive DetectionResult is one review trigger even if a runtime omits
        # trigger details. Multiple detector triggers remain visible as extra volume.
        trigger_count = max(1, len(triggers)) if detected else 0
        return DetectionDecision(detected=detected, trigger_count=trigger_count)


@dataclass(frozen=True)
class _DetectionStats:
    metrics: "DetectionMetrics"
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int


@dataclass(frozen=True)
class DetectionMetrics:
    precision: float
    recall: float | None
    f1: float | None
    false_positive_count: int
    false_positive_rate: float
    trigger_volume: int

    def to_mapping(self) -> dict[str, float | int | None]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "false_positive_count": self.false_positive_count,
            "false_positive_rate": self.false_positive_rate,
            "trigger_volume": self.trigger_volume,
        }


class DetectionPolicyEvaluator:
    policy_type = PolicyType.DETECTION

    def __init__(
        self,
        runner: DetectionRunner,
        gate_provider: DetectionGateProvider,
    ) -> None:
        self._runner = runner
        self._gate_provider = gate_provider

    def evaluate(self, job: EvaluationJob) -> PolicyEvaluationOutcome:
        cases = _detection_cases(job)
        baseline_decisions = self._run_baseline(job, cases)
        baseline_stats = _calculate_stats(cases, baseline_decisions)

        try:
            candidate_decisions = tuple(
                self._validated_decision(
                    self._runner.run(job.plan.candidate_policy_ref, case.input)
                )
                for case in cases
            )
        except Exception as exc:  # Runtime boundary: implementation validity failure.
            return PolicyEvaluationOutcome(
                passed=False,
                implementation_valid=False,
                candidate_metrics=_empty_metrics().to_mapping(),
                baseline_metrics=baseline_stats.metrics.to_mapping(),
                incremental_value={},
                failure_reasons=(
                    f"Candidate implementation failed: {type(exc).__name__}: {exc}",
                ),
            )

        candidate_stats = _calculate_stats(cases, candidate_decisions)
        incremental = _calculate_incremental(
            cases, baseline_decisions, candidate_decisions, baseline_stats, candidate_stats
        )
        regressions = _describe_regressions(incremental)
        failure_reasons = _apply_gates(
            self._gate_provider.get(), candidate_stats.metrics, incremental
        )
        return PolicyEvaluationOutcome(
            passed=not failure_reasons,
            implementation_valid=True,
            candidate_metrics=candidate_stats.metrics.to_mapping(),
            baseline_metrics=baseline_stats.metrics.to_mapping(),
            incremental_value=incremental,
            regressions=regressions,
            failure_reasons=failure_reasons,
        )

    def _run_baseline(
        self, job: EvaluationJob, cases: tuple[DetectionCase, ...]
    ) -> tuple[DetectionDecision, ...]:
        try:
            return tuple(
                self._validated_decision(
                    self._runner.run(job.plan.baseline_policy_ref, case.input)
                )
                for case in cases
            )
        except Exception as exc:
            raise BaselineExecutionError(
                f"Baseline policy {job.plan.baseline_policy_ref!r} could not run: {exc}"
            ) from exc

    @staticmethod
    def _validated_decision(decision: DetectionDecision) -> DetectionDecision:
        if not isinstance(decision, DetectionDecision):
            raise TypeError("Detection runner must return DetectionDecision")
        return decision


def _detection_cases(job: EvaluationJob) -> tuple[DetectionCase, ...]:
    cases: list[DetectionCase] = []
    seen_ids: set[str] = set()
    for dataset in job.datasets:
        for record in dataset.records:
            if not isinstance(record, DetectionCase):
                raise DatasetAccessError(
                    f"Dataset {dataset.ref.ref!r} contains a non-detection record"
                )
            if record.input.case_id in seen_ids:
                raise DatasetAccessError(
                    f"Duplicate case_id across evaluation datasets: {record.input.case_id}"
                )
            seen_ids.add(record.input.case_id)
            cases.append(record)
    if not cases:
        raise DatasetAccessError("Detection evaluation requires at least one case")
    return tuple(cases)


def _calculate_stats(
    cases: tuple[DetectionCase, ...], decisions: tuple[DetectionDecision, ...]
) -> _DetectionStats:
    if len(cases) != len(decisions):
        raise ValueError("Every case must have exactly one decision")

    tp = fp = tn = fn = 0
    for case, decision in zip(cases, decisions, strict=True):
        if case.is_fraud is True:
            if decision.detected:
                tp += 1
            else:
                fn += 1
        elif case.is_fraud is False:
            if decision.detected:
                fp += 1
            else:
                tn += 1

    precision = _ratio(tp, tp + fp, default=0.0)
    recall = _ratio(tp, tp + fn, default=None)
    if recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    metrics = DetectionMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_count=fp,
        # The shared schema does not permit null here; zero is the neutral value
        # when a dataset contains no labelled negatives.
        false_positive_rate=_ratio(fp, fp + tn, default=0.0),
        trigger_volume=sum(decision.trigger_count for decision in decisions),
    )
    return _DetectionStats(
        metrics=metrics,
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
    )


def _calculate_incremental(
    cases: tuple[DetectionCase, ...],
    baseline: tuple[DetectionDecision, ...],
    candidate: tuple[DetectionDecision, ...],
    baseline_stats: _DetectionStats,
    candidate_stats: _DetectionStats,
) -> dict[str, int | float | None]:
    new_fraud_hits = additional_false_positives = fraud_hits_lost = 0
    false_positives_removed = 0
    for case, old, new in zip(cases, baseline, candidate, strict=True):
        if case.is_fraud is True:
            new_fraud_hits += int(new.detected and not old.detected)
            fraud_hits_lost += int(old.detected and not new.detected)
        elif case.is_fraud is False:
            additional_false_positives += int(new.detected and not old.detected)
            false_positives_removed += int(old.detected and not new.detected)

    old_metrics = baseline_stats.metrics
    new_metrics = candidate_stats.metrics
    return {
        "new_fraud_hits": new_fraud_hits,
        "additional_false_positives": additional_false_positives,
        "fraud_hits_lost": fraud_hits_lost,
        "false_positives_removed": false_positives_removed,
        "trigger_volume_delta": new_metrics.trigger_volume - old_metrics.trigger_volume,
        "precision_delta": new_metrics.precision - old_metrics.precision,
        "recall_delta": _optional_delta(new_metrics.recall, old_metrics.recall),
        "f1_delta": _optional_delta(new_metrics.f1, old_metrics.f1),
        "false_positive_count_delta": (
            new_metrics.false_positive_count - old_metrics.false_positive_count
        ),
        "false_positive_rate_delta": (
            new_metrics.false_positive_rate - old_metrics.false_positive_rate
        ),
    }


def _describe_regressions(
    incremental: Mapping[str, int | float | None],
) -> tuple[str, ...]:
    regressions: list[str] = []
    lost = int(incremental["fraud_hits_lost"] or 0)
    added_fp = int(incremental["additional_false_positives"] or 0)
    volume_delta = int(incremental["trigger_volume_delta"] or 0)
    precision_delta = incremental["precision_delta"]
    recall_delta = incremental["recall_delta"]

    if lost:
        regressions.append(f"Candidate loses {lost} fraud hits relative to baseline.")
    if added_fp:
        regressions.append(
            f"Candidate adds {added_fp} false positives relative to baseline."
        )
    if isinstance(precision_delta, (int, float)) and precision_delta < 0:
        regressions.append(f"Candidate precision decreases by {abs(precision_delta):.3f}.")
    if isinstance(recall_delta, (int, float)) and recall_delta < 0:
        regressions.append(f"Candidate recall decreases by {abs(recall_delta):.3f}.")
    if volume_delta > 0:
        regressions.append(f"Candidate trigger volume increases by {volume_delta}.")
    return tuple(regressions)


def _apply_gates(
    gates: DetectionGateConfig,
    candidate: DetectionMetrics,
    incremental: Mapping[str, int | float | None],
) -> tuple[str, ...]:
    failures: list[str] = []
    added_fp = int(incremental["additional_false_positives"] or 0)
    lost = int(incremental["fraud_hits_lost"] or 0)
    volume_delta = int(incremental["trigger_volume_delta"] or 0)
    recall_delta = incremental["recall_delta"]

    if candidate.precision < gates.minimum_precision:
        failures.append(
            f"Precision {candidate.precision:.3f} is below temporary minimum "
            f"{gates.minimum_precision:.3f}."
        )
    if candidate.false_positive_rate > gates.maximum_false_positive_rate:
        failures.append(
            f"False-positive rate {candidate.false_positive_rate:.3f} exceeds temporary "
            f"maximum {gates.maximum_false_positive_rate:.3f}."
        )
    if added_fp > gates.maximum_additional_false_positives:
        failures.append(
            f"Candidate adds {added_fp} false positives; temporary maximum is "
            f"{gates.maximum_additional_false_positives}."
        )
    if lost > gates.maximum_fraud_hits_lost:
        failures.append(
            f"Candidate loses {lost} fraud hits; temporary maximum is "
            f"{gates.maximum_fraud_hits_lost}."
        )
    if volume_delta > gates.maximum_trigger_volume_delta:
        failures.append(
            f"Trigger-volume delta {volume_delta} exceeds temporary maximum "
            f"{gates.maximum_trigger_volume_delta}."
        )
    if isinstance(recall_delta, (int, float)) and recall_delta < gates.minimum_recall_delta:
        failures.append(
            f"Recall delta {recall_delta:.3f} is below temporary minimum "
            f"{gates.minimum_recall_delta:.3f}."
        )
    if gates.require_incremental_improvement:
        new_hits = int(incremental["new_fraud_hits"] or 0)
        removed_fp = int(incremental["false_positives_removed"] or 0)
        if new_hits == 0 and removed_fp == 0:
            failures.append(
                "Candidate provides no incremental fraud hits or false-positive reduction."
            )
    return tuple(failures)


def _ratio(numerator: int, denominator: int, default: float | None) -> float | None:
    return numerator / denominator if denominator else default


def _optional_delta(new: float | None, old: float | None) -> float | None:
    if new is None or old is None:
        return None
    return new - old


def _empty_metrics() -> DetectionMetrics:
    return DetectionMetrics(
        precision=0.0,
        recall=None,
        f1=None,
        false_positive_count=0,
        false_positive_rate=0.0,
        trigger_volume=0,
    )
