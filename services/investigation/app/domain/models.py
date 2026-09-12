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


class ScoreboardConfigRef(StrictModel):
    """Immutable System-owned scoreboard configuration reference."""

    version: str = Field(min_length=1)
    config_id: Optional[str] = Field(default=None, min_length=1)
    content_hash: Optional[str] = Field(default=None, min_length=1)


class InvestigationRequest(StrictModel):
    case_id: str = Field(min_length=1)
    detection_result: DetectionResult
    existing_evidence: list[Evidence] = Field(default_factory=list)
    scoreboard_config_ref: ScoreboardConfigRef


class AgentInvocation(StrictModel):
    agent: str
    case_type: str
    sequence: int = Field(ge=1)
    routing_score: int = Field(ge=0)
    reason: str


class AgentAnalysis(StrictModel):
    """Structured, evidence-bound output requested from every specialist agent."""

    summary: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)
    item_scores: list["AgentItemScore"] = Field(default_factory=list)
    direct_evidence_found: bool = False
    recommended_follow_up: Optional[str] = None

    @model_validator(mode="after")
    def reject_duplicate_item_scores(self) -> "AgentAnalysis":
        names = [item.item_type for item in self.item_scores]
        if len(names) != len(set(names)):
            raise ValueError("item_scores must contain unique item_type values")
        return self


class AgentItemScore(StrictModel):
    """Raw specialist score for one evidence-backed investigation dimension."""

    item_type: str = Field(min_length=1)
    score: int = Field(ge=0, le=5)
    is_direct_evidence: bool
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)

    _unique_evidence_refs = field_validator("evidence_refs")(_require_unique)


class WeightedItemContribution(StrictModel):
    item_type: str
    score: int = Field(ge=0, le=5)
    is_direct_evidence: bool
    confidence: float = Field(ge=0, le=1)
    configured_weight: float = Field(gt=0)
    effective_weight: float = Field(ge=0)
    weighted_contribution: float = Field(ge=0)
    evidence_refs: list[str]


class AgentScoreAggregate(StrictModel):
    weighted_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    total_effective_weight: float = Field(gt=0)
    contributions: list[WeightedItemContribution]


class SpecialistAgentResult(StrictModel):
    """Processed result delivered to the orchestrator with raw output intact."""

    agent: str
    raw_analysis: AgentAnalysis
    score_aggregate: Optional[AgentScoreAggregate] = None
    rejected_item_scores: int = Field(default=0, ge=0)


class ToolDefinition(StrictModel):
    """A gateway-discovered tool that may be exposed to one specialist."""

    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(StrictModel):
    """Auditable record of a model-requested tool execution."""

    name: str = Field(min_length=1)
    arguments: dict[str, Any]
    succeeded: bool
    payload: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class AgentRun(StrictModel):
    agent: str
    analysis: AgentAnalysis
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    tool_calls: list[ToolCallResult] = Field(default_factory=list)


class ScoreboardBudget(StrictModel):
    max_agent_calls: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)
    max_investigation_steps: int = Field(ge=0)
    max_tokens: int = Field(ge=0)
    max_cost_usd: float = Field(ge=0)


class StoppingRule(StrictModel):
    rule_id: str = Field(min_length=1)
    enabled: bool
    priority: int = Field(ge=0)
    parameters: dict[str, Any]


class AgentPolicy(StrictModel):
    agent_id: str = Field(min_length=1)
    enabled: bool
    priority: int = Field(ge=0)
    cost_weight: float = Field(ge=0)


class ScoreboardConfig(StrictModel):
    config_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["draft", "active", "retired"]
    scoring_policy_version: str = Field(min_length=1)
    fraud_threshold: float = Field(default=0.8, ge=0, le=1)
    normal_threshold: float = Field(default=0.2, ge=0, le=1)
    budget: ScoreboardBudget
    stopping_rules: list[StoppingRule] = Field(min_length=1)
    agents: list[AgentPolicy]
    created_at: datetime
    created_by: str = Field(min_length=1)
    note: Optional[str] = None

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "ScoreboardConfig":
        if self.normal_threshold >= self.fraud_threshold:
            raise ValueError("normal_threshold must be below fraud_threshold")
        return self

    def stopping_parameter(self, rule_id: str, key: str, default: Any) -> Any:
        for rule in sorted(self.stopping_rules, key=lambda item: item.priority):
            if rule.enabled and rule.rule_id == rule_id:
                return rule.parameters.get(key, default)
        return default

    def stopping_rule_enabled(self, rule_id: str) -> bool:
        return any(
            rule.enabled and rule.rule_id == rule_id for rule in self.stopping_rules
        )

    @property
    def initial_score(self) -> float:
        return 0.5

    @property
    def finding_weight(self) -> float:
        return 0.2

    @property
    def direct_evidence_confidence(self) -> float:
        return float(self.stopping_parameter("direct_evidence", "minimum_confidence", 0.95))

    @property
    def max_agent_calls(self) -> int:
        return self.budget.max_agent_calls

    @property
    def max_tool_calls(self) -> int:
        return self.budget.max_tool_calls

    @property
    def max_steps(self) -> int:
        return self.budget.max_investigation_steps

    @property
    def max_total_tokens(self) -> int:
        return self.budget.max_tokens

    @property
    def max_output_tokens_per_agent(self) -> int:
        return min(1200, self.budget.max_tokens)

    @property
    def minimum_score_delta(self) -> float:
        return float(self.stopping_parameter("diminishing_returns", "minimum_score_delta", 0.02))

    @property
    def diminishing_return_rounds(self) -> int:
        return int(self.stopping_parameter("diminishing_returns", "rounds", 2))

    @property
    def agent_priorities(self) -> dict[str, int]:
        return {
            agent.agent_id: agent.priority
            for agent in self.agents
            if agent.enabled
        }


class ScoreSnapshot(StrictModel):
    step: int = Field(ge=0)
    agent: str
    score: float = Field(ge=0, le=1)
    delta: float


class ScoreboardUsage(StrictModel):
    agent_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    investigation_steps: int = Field(ge=0)
    tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)


class AgentUsage(StrictModel):
    agent_id: str
    calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)


class ScoreboardState(StrictModel):
    status: Literal["running", "stopped"]
    config_ref: ScoreboardConfigRef
    scoring_policy_version: str
    fraud_score: float = Field(ge=0, le=1)
    usage: ScoreboardUsage
    budget: ScoreboardBudget
    agent_usage: list[AgentUsage]
    stop_reason: Optional[StopReason]
    updated_at: datetime


class InvestigationResult(StrictModel):
    case_id: str
    subject: Subject
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    summary: str
    findings: list[Finding]
    evidence: list[Evidence]
    agents_invoked: list[AgentInvocation]
    agent_results: list[SpecialistAgentResult]
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
