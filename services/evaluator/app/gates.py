from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class DetectionGateConfig:
    """Trusted, temporary hackathon thresholds for detection effectiveness."""

    minimum_precision: float
    maximum_false_positive_rate: float
    maximum_additional_false_positives: int
    maximum_fraud_hits_lost: int
    maximum_trigger_volume_delta: int
    minimum_recall_delta: float
    require_incremental_improvement: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("minimum_precision", self.minimum_precision),
            ("maximum_false_positive_rate", self.maximum_false_positive_rate),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        for name, value in (
            ("maximum_additional_false_positives", self.maximum_additional_false_positives),
            ("maximum_fraud_hits_lost", self.maximum_fraud_hits_lost),
            ("maximum_trigger_volume_delta", self.maximum_trigger_volume_delta),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if not -1 <= self.minimum_recall_delta <= 1:
            raise ValueError("minimum_recall_delta must be between -1 and 1")


class DetectionGateProvider(Protocol):
    def get(self) -> DetectionGateConfig: ...


class StaticDetectionGateProvider:
    """Immutable provider created by trusted evaluator composition code."""

    def __init__(self, config: DetectionGateConfig) -> None:
        self._config = config

    def get(self) -> DetectionGateConfig:
        return self._config


def load_trusted_detection_gates(path: Path) -> DetectionGateConfig:
    """Load evaluator-owned config. Never call this with a candidate-supplied path."""

    with path.open(encoding="utf-8") as config_file:
        payload = json.load(config_file)

    if payload.get("temporary_hackathon_configuration") is not True:
        raise ValueError("Detection gate config must be marked as temporary hackathon config")
    gates = payload["detection_gates"]
    return DetectionGateConfig(
        minimum_precision=float(gates["minimum_precision"]),
        maximum_false_positive_rate=float(gates["maximum_false_positive_rate"]),
        maximum_additional_false_positives=int(
            gates["maximum_additional_false_positives"]
        ),
        maximum_fraud_hits_lost=int(gates["maximum_fraud_hits_lost"]),
        maximum_trigger_volume_delta=int(gates["maximum_trigger_volume_delta"]),
        minimum_recall_delta=float(gates["minimum_recall_delta"]),
        require_incremental_improvement=bool(gates["require_incremental_improvement"]),
    )
