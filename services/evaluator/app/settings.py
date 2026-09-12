"""Environment-backed settings for evaluator execution adapters."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class DetectionHttpSettings:
    base_url: str
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise ValueError("Detection base URL must be a non-empty string")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("Detection base URL must use HTTP or HTTPS")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Detection timeout must be a positive finite number")

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> "DetectionHttpSettings":
        values = os.environ if environ is None else environ
        try:
            base_url = values["DETECTION_URL"]
        except KeyError as exc:
            raise ValueError("DETECTION_URL must be configured for the evaluator") from exc

        timeout_value = values.get("DETECTION_TIMEOUT_SECONDS", "5")
        try:
            timeout_seconds = float(timeout_value)
        except ValueError as exc:
            raise ValueError("DETECTION_TIMEOUT_SECONDS must be numeric") from exc
        return cls(base_url=base_url, timeout_seconds=timeout_seconds)
