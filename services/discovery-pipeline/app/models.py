from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


SubjectType = Literal["account", "shop", "product", "order", "transaction", "message"]
EvidenceSource = Literal[
    "environment", "detection", "investigation", "patrol", "association", "external"
]


class Subject(StrictModel):
    type: SubjectType
    id: str = Field(min_length=1)


class Evidence(StrictModel):
    id: str = Field(min_length=1)
    source: EvidenceSource
    type: str = Field(min_length=1)
    ref_id: str | None = None
    observed_at: datetime | None = None
    data: dict[str, Any]


class PatrolScope(StrictModel):
    subject_types: list[Literal["account", "shop", "product", "transaction", "message"]] = (
        Field(default_factory=list)
    )
    since: datetime | None = None


class PatrolRequest(StrictModel):
    run_id: str = Field(min_length=1)
    mode: Literal["scheduled", "manual"]
    strategy: Literal["exploit", "explore"] = "exploit"
    scope: PatrolScope


class ObservedSignal(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_refs: list[str]

    @field_validator("evidence_refs")
    @classmethod
    def unique_refs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_refs must be unique")
        return value


class PatrolDiscovery(StrictModel):
    subject: Subject
    hypothesis: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    observed_signals: list[ObservedSignal] = Field(min_length=1)
    counter_signals: list[str] = Field(default_factory=list)
    priority: float = Field(ge=0, le=1)
    evidence_refs: list[str]

    @field_validator("evidence_refs")
    @classmethod
    def unique_refs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_refs must be unique")
        return value


class PatrolPolicyRef(StrictModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class PatrolResult(StrictModel):
    run_id: str = Field(min_length=1)
    strategy: Literal["exploit", "explore"]
    policy_ref: PatrolPolicyRef
    discoveries: list[PatrolDiscovery]
    evidence: list[Evidence]


class Indicator(StrictModel):
    type: Literal[
        "ip", "device", "email", "phone", "url", "domain", "payment_account", "shop", "account", "other"
    ]
    value: str = Field(min_length=1)
    evidence_refs: list[str]


class AssociationRequest(StrictModel):
    case_id: str = Field(min_length=1)
    subject: Subject
    strategy: Literal["focused", "discovery"] = "focused"
    seed_indicators: list[Indicator] = Field(default_factory=list)


class AssociationPolicyRef(StrictModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class GraphNode(StrictModel):
    id: str = Field(min_length=1)
    type: Literal[
        "account", "shop", "product", "device", "ip", "payment_account", "domain", "url",
        "conversation", "order", "transaction", "message", "other"
    ]
    label: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    type: str = Field(min_length=1)
    relationship: Literal["observed", "inferred"] = "observed"
    value: str | None = None
    confidence: float = Field(ge=0, le=1)
    occurrence_count: int | None = Field(default=None, ge=1)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    evidence_refs: list[str]


class RelationPath(StrictModel):
    nodes: list[str] = Field(min_length=2)
    edge_types: list[str] = Field(min_length=1)
    evidence_refs: list[str]


class RelatedSubject(StrictModel):
    subject: Subject
    association_score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    relation_paths: list[RelationPath] = Field(min_length=1)
    evidence_refs: list[str]


class AssociationResult(StrictModel):
    case_id: str = Field(min_length=1)
    strategy: Literal["focused", "discovery"]
    policy_ref: AssociationPolicyRef
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    related_subjects: list[RelatedSubject]
    evidence: list[Evidence]


class DetectionPolicyRef(StrictModel):
    type: Literal["detection"] = "detection"
    version: str = Field(min_length=1)


class DetectionTrigger(StrictModel):
    type: str
    detector: Literal["rule_based", "anomaly", "llm_classifier", "ml_classifier"]
    rule_id: str | None = None
    reason: str
    raw_result: dict[str, Any] | None = None
    evidence_refs: list[str]


class ComponentResult(StrictModel):
    component_id: str = Field(min_length=1)
    detector: Literal["rule_based", "anomaly", "llm_classifier", "ml_classifier"]
    version: str = Field(min_length=1)
    status: Literal["completed", "abstained", "unavailable", "failed"]
    trigger_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    reason: str | None = None


class DetectionResult(StrictModel):
    detection_id: str
    subject: Subject
    policy_ref: DetectionPolicyRef
    detected: bool
    triggers: list[DetectionTrigger]
    evidence: list[Evidence]
    component_results: list[ComponentResult]


class ScoreboardConfigRef(StrictModel):
    version: str = Field(min_length=1)
    config_id: str | None = Field(default=None, min_length=1)
    content_hash: str | None = Field(default=None, min_length=1)


class InvestigationRequest(StrictModel):
    case_id: str = Field(min_length=1)
    detection_result: DetectionResult
    existing_evidence: list[Evidence] = Field(default_factory=list)
    scoreboard_config_ref: ScoreboardConfigRef


StageStatus = Literal["succeeded", "failed", "skipped"]


class PipelineError(StrictModel):
    kind: str = Field(min_length=1)
    message: str = Field(min_length=1)


class PatrolStage(StrictModel):
    status: StageStatus
    request: PatrolRequest
    result: PatrolResult | None = None
    started_at: datetime
    completed_at: datetime
    error: PipelineError | None = None


class AssociationStage(StrictModel):
    status: StageStatus
    request: AssociationRequest | None = None
    result: AssociationResult | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: PipelineError | None = None


class InvestigationStage(StrictModel):
    status: StageStatus
    request: InvestigationRequest | None = None
    result: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: PipelineError | None = None


class DiscoveryPipelineItem(StrictModel):
    subject: Subject
    case_id: str
    patrol_discovery: PatrolDiscovery
    association: AssociationStage
    investigation: InvestigationStage


class UpstreamPipelineResult(StrictModel):
    pipeline_run_id: str
    patrol_run_id: str
    status: Literal["succeeded", "partial_failure", "failed"]
    started_at: datetime
    completed_at: datetime
    patrol: PatrolStage
    discoveries: list[DiscoveryPipelineItem]


class InvestigationWithProvenance(StrictModel):
    patrol_run_id: str
    case_id: str
    subject: Subject
    patrol_discovery: PatrolDiscovery
    association: AssociationResult
    investigation_result: dict[str, Any]
