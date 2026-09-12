"""HTTP models mirroring the shared Detection contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SubjectType = Literal["account", "shop", "product", "order", "transaction", "message"]
DetectorType = Literal["rule_based", "anomaly", "llm_classifier", "ml_classifier"]
EvidenceSource = Literal[
    "environment", "detection", "investigation", "patrol", "association", "external"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _unique(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError("items must be unique")
    return values


class Subject(StrictModel):
    type: SubjectType
    id: str = Field(min_length=1)


class PolicyRef(StrictModel):
    type: Literal["detection"]
    version: str = Field(min_length=1)


class TriggerContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: Literal["patrol", "manual", "scheduled", "api"] = "api"
    reason: str | None = None


class DetectionRequest(StrictModel):
    subject: Subject
    trigger_context: TriggerContext = Field(default_factory=TriggerContext)
    requested_checks: list[DetectorType] = Field(default_factory=list)
    policy_ref: PolicyRef = Field(
        default_factory=lambda: PolicyRef(type="detection", version="baseline-v1")
    )

    _unique_checks = field_validator("requested_checks")(_unique)


class Evidence(StrictModel):
    id: str = Field(min_length=1)
    source: EvidenceSource
    type: str = Field(min_length=1)
    ref_id: str | None = None
    observed_at: datetime | None = None
    data: dict[str, Any]


class DetectionTrigger(StrictModel):
    type: str
    detector: DetectorType
    rule_id: str | None = None
    reason: str
    raw_result: dict[str, Any] | None = None
    evidence_refs: list[str]

    _unique_evidence_refs = field_validator("evidence_refs")(_unique)


class ComponentResult(StrictModel):
    component_id: str
    detector: DetectorType
    version: str
    status: Literal["completed", "abstained", "unavailable", "failed"]
    trigger_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    reason: str | None = None


class DetectionResult(StrictModel):
    detection_id: str
    subject: Subject
    policy_ref: PolicyRef
    detected: bool
    triggers: list[DetectionTrigger]
    evidence: list[Evidence]
    component_results: list[ComponentResult] = Field(default_factory=list)


class HealthResponse(StrictModel):
    status: Literal["ok"]
    service: str


class ReadinessResponse(StrictModel):
    status: Literal["ready"]
    dependencies: dict[str, Literal["ok"]]


class ErrorDetail(StrictModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(StrictModel):
    error: ErrorDetail
