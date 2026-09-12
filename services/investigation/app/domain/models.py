"""HTTP models mirroring the shared investigation contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SubjectType = Literal["account", "shop", "product", "order", "transaction", "message"]
EvidenceSource = Literal[
    "environment", "detection", "investigation", "patrol", "association", "external"
]
FindingImpact = Literal["supports_fraud", "supports_legitimate", "neutral"]
Verdict = Literal["fraud", "suspicious", "normal", "unknown"]
StopReason = Literal[
    "direct_evidence",
    "fraud_threshold",
    "false_positive_evidence",
    "budget_exhausted",
    "diminishing_returns",
    "insufficient_evidence",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_unique(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError("items must be unique")
    return values


class Subject(StrictModel):
    type: SubjectType
    id: str = Field(min_length=1)


class Evidence(StrictModel):
    id: str = Field(min_length=1)
    source: EvidenceSource
    type: str = Field(min_length=1)
    ref_id: Optional[str] = None
    observed_at: Optional[datetime] = None
    data: dict[str, Any]


class Finding(StrictModel):
    type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    impact: FindingImpact
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str]

    _unique_evidence_refs = field_validator("evidence_refs")(_require_unique)


class DetectionTrigger(StrictModel):
    type: str
    detector: Literal["rule_based", "anomaly", "llm_classifier", "ml_classifier"]
    rule_id: Optional[str] = None
    reason: str
    raw_result: Optional[dict[str, Any]] = None
    evidence_refs: list[str]

    _unique_evidence_refs = field_validator("evidence_refs")(_require_unique)


class PolicyRef(StrictModel):
    type: Literal["detection"]
    version: str


class ComponentResult(StrictModel):
    component_id: str
    detector: Literal["rule_based", "anomaly", "llm_classifier", "ml_classifier"]
    version: str
    status: Literal["completed", "abstained", "unavailable", "failed"]
    trigger_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    reason: Optional[str] = None


class DetectionResult(StrictModel):
    detection_id: str
    subject: Subject
    policy_ref: PolicyRef
    detected: bool
    triggers: list[DetectionTrigger]
    evidence: list[Evidence]
    component_results: list[ComponentResult] = Field(default_factory=list)


class ScoreboardConfigRef(BaseModel):
    """Flexible until the System-owned scoreboard schema is available."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def reject_empty_reference(self) -> "ScoreboardConfigRef":
        if not self.model_extra:
            raise ValueError("scoreboard_config_ref must not be empty")
        return self


class InvestigationRequest(StrictModel):
    case_id: str = Field(min_length=1)
    detection_result: DetectionResult
    existing_evidence: list[Evidence] = Field(default_factory=list)
    scoreboard_config_ref: ScoreboardConfigRef


class AgentInvocation(StrictModel):
    agent: str
    reason: str


class InvestigationResult(StrictModel):
    case_id: str
    subject: Subject
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    summary: str
    findings: list[Finding]
    evidence: list[Evidence]
    agents_invoked: list[AgentInvocation]
    scoreboard: dict[str, Any]
    stop_reason: StopReason


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
