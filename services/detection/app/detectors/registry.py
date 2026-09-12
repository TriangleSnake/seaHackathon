from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RegisteredDetector:
    detector_type: str
    version: str
    required_evidence: frozenset[str]
    factory: Callable[[dict[str, Any]], Any]


class DetectorRegistry:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], RegisteredDetector] = {}

    def register(self, detector: RegisteredDetector) -> None:
        key = (detector.detector_type, detector.version)
        if key in self._items:
            raise ValueError(f"Detector already registered: {key}")
        self._items[key] = detector

    def resolve(self, detector_type: str, version: str) -> RegisteredDetector | None:
        return self._items.get((detector_type, version))
