"""Strict internal contracts for evidence-grounded pattern synthesis."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Verdict = Literal["fraud", "suspicious", "normal", "unknown"]
PolicyType = Literal[
    "detection", "scoring", "investigation", "exploration", "association"
]
SignalOperator = Literal[
    "eq", "neq", "gt", "gte", "lt", "lte", "contains", "regex", "in"
]
SignalValue = str | int | float | bool | list[str]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


class Finding(StrictModel):
    type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    impact: Literal["supports_fraud", "supports_legitimate", "neutral"]
    confidence: float = Field(ge=0, le=1)
    evidence_refs: tuple[str, ...]


class InvestigationResult(StrictModel):
    """Stable Investigation response; deep fields are checked against shared JSON Schema."""

    case_id: str = Field(min_length=1)
    subject: Subject
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    summary: str
    findings: tuple[Finding, ...]
    evidence: tuple[Evidence, ...]
    agents_invoked: tuple[dict[str, Any], ...]
    agent_results: tuple[dict[str, Any], ...]
    scoreboard: dict[str, Any]
    stop_reason: Literal[
        "direct_evidence",
        "fraud_threshold",
        "false_positive_evidence",
        "budget_exhausted",
        "diminishing_returns",
        "insufficient_evidence",
    ]


class DefenseVersionRef(FrozenStrictModel):
    version: str = Field(min_length=1)


class PolicyRef(FrozenStrictModel):
    type: PolicyType
    version: str = Field(min_length=1)


class PolicyCapability(FrozenStrictModel):
    capability_id: str = Field(min_length=1)
    policy_type: PolicyType
    kind: Literal["CONFIG", "CODE", "UNSUPPORTED"]
    surface: str = Field(min_length=1)
    description: str = Field(min_length=1)
    constraints: tuple[str, ...] = ()


class PolicyCapabilitySummary(FrozenStrictModel):
    summary: str = Field(min_length=1)
    capabilities: tuple[PolicyCapability, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_capability_ids(self) -> "PolicyCapabilitySummary":
        values = [item.capability_id for item in self.capabilities]
        if len(values) != len(set(values)):
            raise ValueError("capability_id values must be unique")
        return self


class PatternSynthesisRequest(FrozenStrictModel):
    synthesis_id: str = Field(min_length=1)
    candidate_results: tuple[InvestigationResult, ...] = Field(min_length=1)
    counterexample_results: tuple[InvestigationResult, ...] = ()
    active_defense_version: DefenseVersionRef
    active_policy_refs: tuple[PolicyRef, ...] = Field(min_length=1)
    policy_capability_summary: PolicyCapabilitySummary
    pattern_hint: str | None = None
    grouping_reason: str | None = None

    @model_validator(mode="after")
    def validate_case_roles(self) -> "PatternSynthesisRequest":
        invalid_candidates = [
            item.case_id
            for item in self.candidate_results
            if item.verdict not in {"fraud", "suspicious"}
        ]
        if invalid_candidates:
            raise ValueError(
                "candidate_results may contain only fraud/suspicious verdicts: "
                + ", ".join(invalid_candidates)
            )
        invalid_counterexamples = [
            item.case_id
            for item in self.counterexample_results
            if item.verdict != "normal"
        ]
        if invalid_counterexamples:
            raise ValueError(
                "counterexample_results may contain only normal verdicts: "
                + ", ".join(invalid_counterexamples)
            )
        case_ids = [
            item.case_id
            for item in (*self.candidate_results, *self.counterexample_results)
        ]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case IDs must be unique across all supplied cases")
        policy_types = [item.type for item in self.active_policy_refs]
        if len(policy_types) != len(set(policy_types)):
            raise ValueError("active_policy_refs may contain only one active version per type")
        unknown_capability_types = {
            item.policy_type for item in self.policy_capability_summary.capabilities
        } - set(policy_types)
        if unknown_capability_types:
            raise ValueError(
                "policy capabilities must belong to an active policy type: "
                + ", ".join(sorted(unknown_capability_types))
            )
        return self

    def semantic_context(self) -> dict[str, Any]:
        """Return a detached, read-only-by-boundary snapshot for the semantic agent."""

        def case_context(item: InvestigationResult) -> dict[str, Any]:
            return item.model_dump(
                mode="json",
                include={
                    "case_id",
                    "subject",
                    "verdict",
                    "confidence",
                    "summary",
                    "findings",
                    "evidence",
                    "stop_reason",
                },
            )

        return {
            "synthesis_id": self.synthesis_id,
            "candidate_cases": [case_context(item) for item in self.candidate_results],
            "counterexample_cases": [
                case_context(item) for item in self.counterexample_results
            ],
            "active_defense_context": {
                "defense_version": self.active_defense_version.model_dump(mode="json"),
                "policy_refs": [
                    item.model_dump(mode="json") for item in self.active_policy_refs
                ],
                "capability_summary": self.policy_capability_summary.model_dump(
                    mode="json"
                ),
            },
            "pattern_hint": self.pattern_hint,
            "grouping_reason": self.grouping_reason,
        }


class GroundedObservedSignal(StrictModel):
    field: str = Field(min_length=1)
    operator: SignalOperator
    value: SignalValue
    description: str | None = None
    grounding_kind: Literal["semantic", "literal"]
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class GroundedBehaviorStep(StrictModel):
    order: int = Field(ge=1)
    action: str = Field(min_length=1)
    description: str | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class SemanticPatternDraft(StrictModel):
    name: str = Field(min_length=1)
    description: str | None = None
    observed_signals: tuple[GroundedObservedSignal, ...] = Field(min_length=1)
    behavior_sequence: tuple[GroundedBehaviorStep, ...] = ()
    supporting_cases: tuple[str, ...] = Field(min_length=2)
    counterexamples: tuple[str, ...] = ()
    current_defense_gap: str = Field(min_length=1)
    defense_capability_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class SemanticSynthesisOutput(StrictModel):
    outcome: Literal["PATTERN", "NO_PATTERN"]
    reason: str = Field(min_length=1)
    pattern: SemanticPatternDraft | None = None

    @model_validator(mode="after")
    def outcome_matches_payload(self) -> "SemanticSynthesisOutput":
        if self.outcome == "PATTERN" and self.pattern is None:
            raise ValueError("PATTERN requires pattern")
        if self.outcome == "NO_PATTERN" and self.pattern is not None:
            raise ValueError("NO_PATTERN cannot include pattern")
        return self


class ObservedSignal(StrictModel):
    field: str
    operator: SignalOperator
    value: Any
    description: str | None = None


class BehaviorStep(StrictModel):
    order: int = Field(ge=1)
    action: str
    description: str | None = None


class PatternSpec(StrictModel):
    pattern_id: str
    name: str
    description: str | None = None
    observed_signals: tuple[ObservedSignal, ...]
    behavior_sequence: tuple[BehaviorStep, ...] = ()
    supporting_cases: tuple[str, ...] = ()
    counterexamples: tuple[str, ...] = ()
    current_defense_gap: str
    evidence_refs: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)


class SignalProvenance(StrictModel):
    signal_index: int = Field(ge=0)
    grounding_kind: Literal["semantic", "literal"]
    evidence_refs: tuple[str, ...]
    supporting_cases: tuple[str, ...]


class BehaviorProvenance(StrictModel):
    step_order: int = Field(ge=1)
    evidence_refs: tuple[str, ...]
    supporting_cases: tuple[str, ...]


class SynthesisProvenance(StrictModel):
    synthesis_id: str
    candidate_case_ids: tuple[str, ...]
    counterexample_case_ids: tuple[str, ...]
    evidence_case_map: dict[str, str]
    active_defense_version: DefenseVersionRef
    active_policy_refs: tuple[PolicyRef, ...]
    defense_capability_refs: tuple[str, ...]
    signal_grounding: tuple[SignalProvenance, ...]
    behavior_grounding: tuple[BehaviorProvenance, ...]


class PatternSynthesisResult(StrictModel):
    status: Literal["PATTERN", "NO_PATTERN"]
    reason: str
    pattern_spec: PatternSpec | None = None
    provenance: SynthesisProvenance | None = None

    @model_validator(mode="after")
    def status_matches_payload(self) -> "PatternSynthesisResult":
        if self.status == "PATTERN" and (
            self.pattern_spec is None or self.provenance is None
        ):
            raise ValueError("PATTERN requires pattern_spec and provenance")
        if self.status == "NO_PATTERN" and (
            self.pattern_spec is not None or self.provenance is not None
        ):
            raise ValueError("NO_PATTERN cannot include pattern_spec or provenance")
        return self


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
    issues: tuple[str, ...] = ()


class ErrorResponse(StrictModel):
    error: ErrorDetail
