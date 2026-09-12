"""External contract adapters and internal governance records."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImmutableStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationMetrics(StrictModel):
    precision: float = Field(ge=0, le=1)
    recall: Optional[float] = Field(default=None, ge=0, le=1)
    f1: Optional[float] = Field(default=None, ge=0, le=1)
    false_positive_count: int = Field(ge=0)
    false_positive_rate: float = Field(ge=0, le=1)
    trigger_volume: int = Field(ge=0)


class EvaluationResult(StrictModel):
    """Adapter mirroring evaluation.schema.json#/$defs/EvaluationResult."""

    evaluation_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    status: Literal["passed", "failed"]
    implementation_valid: bool
    candidate_metrics: EvaluationMetrics
    baseline_metrics: EvaluationMetrics
    incremental_value: dict[str, Optional[float | int]]
    regressions: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)


class GovernanceRequest(StrictModel):
    """Adapter mirroring the existing shared GovernanceRequest contract."""

    candidate_id: str = Field(min_length=1)
    evaluation: EvaluationResult
    requested_by: Optional[str] = None
    require_human_approval: bool = False

    @model_validator(mode="after")
    def candidate_must_match_evaluation(self) -> "GovernanceRequest":
        if self.candidate_id != self.evaluation.candidate_id:
            raise ValueError("candidate_id must match evaluation.candidate_id")
        return self


class GovernanceDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    NEEDS_REVIEW = "needs_review"


class PolicyCheckResult(ImmutableStrictModel):
    name: str = Field(min_length=1)
    passed: bool
    reason: Optional[str] = None


class GovernanceResult(StrictModel):
    """Schema-compatible authorization only; never a version promotion result."""

    decision: GovernanceDecision
    reason: str
    policy_checks: list[PolicyCheckResult] = Field(default_factory=list)
    approved_defense_version: None = None


class GovernancePolicyConfig(ImmutableStrictModel):
    """Trusted, externally supplied policy. Provisional defaults are for demos/tests."""

    require_human_approval: bool = False
    block_reported_regressions: bool = True


class HumanReviewInput(StrictModel):
    candidate_id: str = Field(min_length=1)
    evaluation_id: str = Field(min_length=1)
    decision: Literal[GovernanceDecision.APPROVE, GovernanceDecision.REJECT]
    reviewer: str = Field(min_length=1)
    reason: Optional[str] = None


class HumanReviewDecision(ImmutableStrictModel):
    candidate_id: str
    evaluation_id: str
    decision: GovernanceDecision
    reviewer: str
    reason: Optional[str]
    recorded_at: datetime


class GovernanceAuditEvent(ImmutableStrictModel):
    event_id: str
    event_type: Literal["system_policy_decision", "human_review_decision"]
    candidate_id: str
    evaluation_id: str
    decision: GovernanceDecision
    reason: str
    actor: Optional[str]
    timestamp: datetime
    policy_checks: tuple[PolicyCheckResult, ...] = ()
    human_reviewer: Optional[str] = None
    previous_decision: Optional[GovernanceDecision] = None


class GovernanceContext(ImmutableStrictModel):
    request: GovernanceRequest
    policy: GovernancePolicyConfig
    human_review: Optional[HumanReviewDecision] = None


class CheckOutcome(ImmutableStrictModel):
    result: PolicyCheckResult
    failure_decision: Optional[GovernanceDecision] = None


JsonObject = dict[str, Any]
