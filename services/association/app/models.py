from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Subject(StrictModel):
    type: Literal["account", "shop", "product", "order", "transaction", "message"]
    id: str = Field(min_length=1)


class Indicator(StrictModel):
    type: Literal["ip", "device", "email", "phone", "url", "domain", "payment_account", "shop", "account", "other"]
    value: str = Field(min_length=1)
    evidence_refs: list[str]


class AssociationRequest(StrictModel):
    case_id: str = Field(min_length=1)
    subject: Subject
    strategy: Literal["focused", "discovery"] = "focused"
    seed_indicators: list[Indicator] = Field(default_factory=list)


class Evidence(StrictModel):
    id: str = Field(min_length=1)
    source: Literal["environment", "detection", "investigation", "patrol", "association", "external"]
    type: str = Field(min_length=1)
    ref_id: str | None = None
    observed_at: datetime | None = None
    data: dict[str, Any]


class PolicyRef(StrictModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class GraphNode(StrictModel):
    id: str = Field(min_length=1)
    type: Literal["account", "shop", "product", "device", "ip", "payment_account", "domain", "url", "conversation", "order", "transaction", "message", "other"]
    label: str | None = None
    association_score: float | None = Field(default=None, ge=0, le=1)
    assessment_reason: str | None = Field(default=None, min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_complete_assessment(self) -> "GraphNode":
        if (self.association_score is None) != (self.assessment_reason is None):
            raise ValueError("association_score and assessment_reason must be supplied together")
        return self


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
    case_id: str
    strategy: Literal["focused", "discovery"]
    policy_ref: PolicyRef
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    related_subjects: list[RelatedSubject]
    evidence: list[Evidence]


class AssociationJobAccepted(StrictModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    status_url: str


class AssociationJobState(StrictModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    case_id: str
    strategy: Literal["focused", "discovery"]
    policy_ref: PolicyRef
    created_at: datetime
    updated_at: datetime
    result: AssociationResult | None = None
    error: str | None = None
    callback_status: Literal["not_configured", "pending", "delivered", "failed"]
    callback_attempts: int = Field(default=0, ge=0)
    callback_error: str | None = None


class SearchPolicy(StrictModel):
    max_hops: int = Field(default=2, ge=1, le=2)
    max_nodes: int = Field(default=100, ge=1, le=100)
    lookback_days: int = Field(default=30, ge=1, le=365)
    minimum_independent_signals: int = Field(default=2, ge=1, le=10)


class AssociationBudget(StrictModel):
    max_turns: int = Field(default=15, ge=1, le=50)
    max_related_subjects: int = Field(default=10, ge=0, le=100)


class AssociationPolicy(StrictModel):
    policy_id: str
    version: str
    strategy: Literal["focused", "discovery"]
    objective: str
    allowed_tools: list[str]
    relation_guidance: list[dict[str, Any]] = Field(default_factory=list)
    search: SearchPolicy = Field(default_factory=SearchPolicy)
    budget: AssociationBudget = Field(default_factory=AssociationBudget)
    stopping_conditions: list[str] = Field(default_factory=list)
