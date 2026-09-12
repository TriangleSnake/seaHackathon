from __future__ import annotations

from collections.abc import Callable

from app.detection import DetectionDecision
from app.errors import DatasetAccessError, EvaluationPlanError
from app.models import (
    DatasetRef,
    DetectionCase,
    DetectionInput,
    EvaluationDataset,
    EvaluationPlan,
)


def detection_cases() -> tuple[DetectionCase, ...]:
    """Four fraud and four legitimate account cases using environment schema fields."""

    return (
        _case("fraud-banned", True, "banned", 0.95, "rejected", 0.92),
        _case("fraud-kyc", True, "active", 0.84, "rejected", 0.72),
        _case("fraud-new-1", True, "active", 0.90, "unverified", 0.92),
        _case("fraud-new-2", True, "active", 0.82, "unverified", 0.86),
        _case("normal-borderline", False, "active", 0.61, "unverified", 0.84),
        _case("normal-verified-1", False, "active", 0.58, "verified", 0.70),
        _case("normal-unverified", False, "active", 0.52, "unverified", 0.60),
        _case("normal-restricted", False, "restricted", 0.49, "verified", 0.45),
    )


def _case(
    case_id: str,
    is_fraud: bool,
    status: str,
    activity_score: float,
    kyc_status: str,
    bot_check_score: float,
) -> DetectionCase:
    return DetectionCase(
        input=DetectionInput(
            case_id=case_id,
            subject_type="account",
            subject_id=f"acct-{case_id}",
            facts={
                "status": status,
                "activity_score": activity_score,
                "kyc_status": kyc_status,
                "bot_check_score": bot_check_score,
            },
        ),
        is_fraud=is_fraud,
    )


class FixtureDatasetSource:
    """TEST FAKE: in-memory labelled source behind production access boundaries."""

    def __init__(self, datasets: tuple[EvaluationDataset, ...]) -> None:
        self._datasets = {dataset.ref: dataset for dataset in datasets}
        self.load_calls: list[DatasetRef] = []

    def load(self, dataset_ref: DatasetRef) -> EvaluationDataset:
        self.load_calls.append(dataset_ref)
        try:
            return self._datasets[dataset_ref]
        except KeyError as exc:
            raise DatasetAccessError(f"Unknown fixture dataset: {dataset_ref.ref}") from exc


class FixtureRuleDetectionRunner:
    """TEST FAKE: deterministic stand-in until the Detection runtime exists."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self._rules: dict[str, Callable[[DetectionInput], bool]] = {
            "detection/baseline-v1": _baseline_rule,
            "detection/candidate-a": _candidate_a_rule,
            "detection/candidate-b": _candidate_b_rule,
        }

    def run(self, policy_ref: str, case_input: DetectionInput) -> DetectionDecision:
        self.calls.append((policy_ref, case_input.case_id, id(case_input)))
        detected = self._rules[policy_ref](case_input)
        return DetectionDecision(detected=detected, trigger_count=int(detected))


class FixturePlanResolver:
    """TEST FAKE: trusted candidate registry/defense-version resolution."""

    def __init__(self, plans: dict[str, EvaluationPlan]) -> None:
        self._plans = plans

    def resolve(self, candidate_id: str, baseline_defense_version: str) -> EvaluationPlan:
        try:
            return self._plans[candidate_id]
        except KeyError as exc:
            raise EvaluationPlanError(f"Unknown candidate: {candidate_id}") from exc


def _baseline_rule(case_input: DetectionInput) -> bool:
    facts = case_input.facts
    return facts["status"] == "banned" or facts["kyc_status"] == "rejected"


def _candidate_a_rule(case_input: DetectionInput) -> bool:
    # Finds both new frauds but is intentionally far too broad.
    return _baseline_rule(case_input) or case_input.facts["bot_check_score"] >= 0.40


def _candidate_b_rule(case_input: DetectionInput) -> bool:
    # Retains the new fraud hits while narrowing the noisy bot signal.
    facts = case_input.facts
    return _baseline_rule(case_input) or (
        facts["bot_check_score"] >= 0.80 and facts["kyc_status"] == "unverified"
    )
