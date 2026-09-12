from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatrolScope(StrictModel):
    subject_types: list[Literal["account", "shop", "product", "transaction", "message"]] = Field(
        default_factory=list
    )
    since: datetime | None = None


class PatrolRequest(StrictModel):
    run_id: str = Field(min_length=1)
    mode: Literal["scheduled", "manual"]
    strategy: Literal["exploit", "explore"] = "exploit"
    scope: PatrolScope


class Subject(StrictModel):
    type: Literal["account", "shop", "product", "order", "transaction", "message"]
    id: str = Field(min_length=1)


class Evidence(StrictModel):
    id: str = Field(min_length=1)
    source: Literal[
        "environment", "detection", "investigation", "patrol", "association", "external"
    ]
    type: str = Field(min_length=1)
    ref_id: str | None = None
    observed_at: datetime | None = None
    data: dict[str, Any]


class ObservedSignal(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_refs: list[str]


class PatrolDiscovery(StrictModel):
    subject: Subject
    hypothesis: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    observed_signals: list[ObservedSignal] = Field(min_length=1)
    counter_signals: list[str] = Field(default_factory=list)
    priority: float = Field(ge=0, le=1)
    evidence_refs: list[str]


class PatrolPolicyRef(StrictModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class PatrolResult(StrictModel):
    run_id: str
    strategy: Literal["exploit", "explore"]
    policy_ref: PatrolPolicyRef
    discoveries: list[PatrolDiscovery]
    evidence: list[Evidence]


class PatrolBudget(StrictModel):
    max_turns: int = Field(default=12, ge=1, le=50)
    max_discoveries: int = Field(default=5, ge=0, le=100)


class PatrolPolicy(StrictModel):
    policy_id: str
    version: str
    strategy: Literal["exploit", "explore"]
    objective: str
    allowed_tools: list[str]
    exploration_guidance: list[str] = Field(default_factory=list)
    evidence_requirements: dict[str, Any] = Field(default_factory=dict)
    budget: PatrolBudget = Field(default_factory=PatrolBudget)
    stopping_conditions: list[str] = Field(default_factory=list)
