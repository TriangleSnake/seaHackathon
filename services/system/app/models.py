from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentComponent = Literal["detection", "investigation", "patrol", "association", "codex-builder"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
ALLOWED_MODELS = {
    "detection": ["gpt-4.1-mini", "gpt-5-mini", "gpt-5.4-mini"],
    "investigation": ["gpt-5-mini", "gpt-5.4-mini", "gpt-5.4"],
    "patrol": ["gpt-5-mini", "gpt-5.4-mini", "gpt-5.4"],
    "association": ["gpt-5-mini", "gpt-5.4-mini", "gpt-5.4"],
    "codex-builder": ["gpt-5.4-mini", "gpt-5.4"],
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Subject(StrictModel):
    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class Trigger(StrictModel):
    type: Literal["event", "schedule", "manual"]
    ref: str = Field(min_length=1)
    event_type: str | None = None


class TriggerPolicy(StrictModel):
    policy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    enabled: bool = False
    event_type: str = Field(min_length=1)
    source: Literal["messages", "login_events", "account_security_events", "payment_attempts", "products"]
    target_agent: Literal["detection"] = "detection"
    subject_type: str = Field(min_length=1)
    subject_id_field: str = Field(min_length=1)
    requested_checks: list[Literal["rule_based", "anomaly", "llm_classifier", "ml_classifier"]] = Field(default_factory=list)
    cooldown_seconds: int = Field(default=0, ge=0)
    batch_size: int = Field(default=100, ge=1, le=1000)
    auto_investigate: bool = False
    updated_at: datetime | None = None


class SystemSchedule(StrictModel):
    schedule_id: str = Field(min_length=1)
    agent: Literal["patrol"] = "patrol"
    enabled: bool = False
    interval_seconds: int = Field(default=900, ge=60, le=2_592_000)
    config: dict[str, Any] = Field(default_factory=lambda: {
        "strategy_weights": {"exploit": 4, "explore": 1},
        "scope": {"subject_types": []},
    })
    next_run_at: datetime | None = None
    run_count: int = Field(default=0, ge=0)
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def valid_weights(self) -> "SystemSchedule":
        weights = self.config.get("strategy_weights", {})
        if not isinstance(weights, dict) or any(not isinstance(weights.get(k), int) or weights[k] < 0 for k in ("exploit", "explore")):
            raise ValueError("strategy_weights must contain non-negative integer exploit and explore weights")
        if weights["exploit"] + weights["explore"] == 0:
            raise ValueError("at least one patrol strategy weight must be positive")
        if not isinstance(self.config.get("scope", {}), dict):
            raise ValueError("scope must be an object")
        return self


class ManualJobRequest(StrictModel):
    agent: Literal["detection", "patrol", "investigation", "association"]
    subject: Subject | None = None
    policy_version: str = Field(default="active", min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class AgentModelConfig(StrictModel):
    component: AgentComponent
    provider: Literal["openai"] = "openai"
    model: str = Field(min_length=1, max_length=100)
    reasoning_effort: ReasoningEffort = "medium"
    enabled: bool = True
    allowed_models: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_model_allowlist(self) -> "AgentModelConfig":
        allowed = ALLOWED_MODELS[self.component]
        if self.model not in allowed:
            raise ValueError(f"model is not allowed for {self.component}")
        self.allowed_models = allowed
        return self


class JobState(StrictModel):
    job_id: str
    agent: Literal["detection", "patrol", "investigation", "association"]
    trigger_type: Literal["event", "schedule", "manual"]
    trigger_ref: str
    event_type: str | None = None
    subject: dict[str, Any] | None = None
    policy_version: str
    status: Literal["queued", "running", "dispatched", "completed", "failed", "dead_letter"]
    attempt: int
    max_attempts: int
    idempotency_key: str
    parent_job_id: str | None = None
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    remote_job_id: str | None = None
    remote_status_url: str | None = None
    error: str | None = None
    available_at: datetime
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class CaseState(StrictModel):
    case_id: str
    investigation_job_id: str
    parent_job_id: str | None = None
    subject: dict[str, Any] | None = None
    status: Literal["investigating", "review", "failed"]
    verdict: Literal["fraud", "suspicious", "normal", "unknown"] = "unknown"
    confidence: float | None = Field(default=None, ge=0, le=1)
    summary: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    agents_invoked: list[dict[str, Any]] = Field(default_factory=list)
    scoreboard: dict[str, Any] = Field(default_factory=dict)
    stop_reason: str | None = None
    detection_result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    updated_at: datetime
