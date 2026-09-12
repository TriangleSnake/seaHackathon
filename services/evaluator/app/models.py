from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class PolicyType(str, Enum):
    DETECTION = "detection"
    SCORING = "scoring"
    EXPLORATION = "exploration"
    INVESTIGATION = "investigation"
    ASSOCIATION = "association"


class DatasetPhase(str, Enum):
    BUILD = "build"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


@dataclass(frozen=True)
class DatasetRef:
    phase: DatasetPhase
    ref: str


@dataclass(frozen=True)
class EvaluationRequest:
    evaluation_id: str
    candidate_id: str
    baseline_defense_version: str
    datasets: tuple[DatasetRef, ...]
    # Retained for shared-contract compatibility only. The service deliberately
    # never passes these caller-controlled values to evaluators or gate providers.
    requested_thresholds: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "requested_thresholds", MappingProxyType(dict(self.requested_thresholds))
        )


@dataclass(frozen=True)
class DetectionInput:
    """Label-free input that is safe to pass to a detection policy runner."""

    case_id: str
    subject_type: str
    subject_id: str
    facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))


@dataclass(frozen=True)
class DetectionCase:
    input: DetectionInput
    is_fraud: bool | None


@dataclass(frozen=True)
class EvaluationDataset:
    ref: DatasetRef
    records: tuple[object, ...]


@dataclass(frozen=True)
class EvaluationPlan:
    """Trusted routing and artifact resolution kept outside candidate input."""

    policy_type: PolicyType
    baseline_defense_version: str
    baseline_policy_ref: str
    candidate_policy_ref: str


@dataclass(frozen=True)
class EvaluationJob:
    evaluation_id: str
    candidate_id: str
    plan: EvaluationPlan
    datasets: tuple[EvaluationDataset, ...]


@dataclass(frozen=True)
class PolicyEvaluationOutcome:
    passed: bool
    implementation_valid: bool
    # Policy evaluators keep their natural domain metrics here. The shared result
    # adapter owns today's detection-oriented compatibility requirements.
    candidate_metrics: Mapping[str, int | float | None]
    baseline_metrics: Mapping[str, int | float | None]
    incremental_value: Mapping[str, int | float | None]
    regressions: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()
