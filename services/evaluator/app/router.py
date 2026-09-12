from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .detection import DetectionPolicyEvaluator
from .errors import UnsupportedPolicyError
from .models import EvaluationJob, PolicyEvaluationOutcome, PolicyType


class PolicyEvaluator(Protocol):
    policy_type: PolicyType

    def evaluate(self, job: EvaluationJob) -> PolicyEvaluationOutcome: ...


class UnsupportedPolicyEvaluator:
    """Explicit placeholder that fails instead of producing fake generic metrics."""

    def __init__(self, policy_type: PolicyType) -> None:
        self.policy_type = policy_type

    def evaluate(self, job: EvaluationJob) -> PolicyEvaluationOutcome:
        raise UnsupportedPolicyError(
            f"Policy evaluator {self.policy_type.value!r} is not implemented"
        )


class EvaluatorRouter:
    def __init__(self, evaluators: Iterable[PolicyEvaluator]) -> None:
        self._evaluators: dict[PolicyType, PolicyEvaluator] = {}
        for evaluator in evaluators:
            if evaluator.policy_type in self._evaluators:
                raise ValueError(
                    f"Duplicate evaluator registration: {evaluator.policy_type.value}"
                )
            self._evaluators[evaluator.policy_type] = evaluator

    def get(self, policy_type: PolicyType) -> PolicyEvaluator:
        try:
            return self._evaluators[policy_type]
        except KeyError as exc:
            raise UnsupportedPolicyError(
                f"No evaluator is registered for {policy_type.value!r}"
            ) from exc


def build_default_router(detection: DetectionPolicyEvaluator) -> EvaluatorRouter:
    """Register all policy identifiers while only implementing detection today."""

    placeholders = (
        UnsupportedPolicyEvaluator(PolicyType.SCORING),
        UnsupportedPolicyEvaluator(PolicyType.EXPLORATION),
        UnsupportedPolicyEvaluator(PolicyType.INVESTIGATION),
        UnsupportedPolicyEvaluator(PolicyType.ASSOCIATION),
    )
    return EvaluatorRouter((detection, *placeholders))
