from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping


class PolicyType(str, Enum):
    DETECTION = "detection"
    SCORING = "scoring"
    EXPLORATION = "exploration"
    INVESTIGATION = "investigation"
    ASSOCIATION = "association"


class TriggerType(str, Enum):
    NEW_SPEC_READY = "new_spec_ready"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    RECURRING = "recurring"


class DiagnosisOutcome(str, Enum):
    CHANGE_NEEDED = "CHANGE_NEEDED"
    NO_ACTION = "NO_ACTION"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


class GapSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CapabilityKind(str, Enum):
    CONFIG = "CONFIG"
    CODE = "CODE"
    UNSUPPORTED = "UNSUPPORTED"


class ConfigListOperation(str, Enum):
    ADD = "add"
    REMOVE = "remove"


DETECTION_CHAT_REQUEST_PHRASES_PATH = "rule_based.chat_request_phrases"
_SAFE_DOTTED_CONFIG_PATH = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
)


class RunState(str, Enum):
    RECEIVED = "RECEIVED"
    DIAGNOSING = "DIAGNOSING"
    PROPOSED = "PROPOSED"
    RESOLVING = "RESOLVING"
    BUILDING = "BUILDING"
    VALIDATING = "VALIDATING"
    REVISING = "REVISING"
    FROZEN = "FROZEN"
    HOLDOUT = "HOLDOUT"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"
    NO_ACTION = "NO_ACTION"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


@dataclass(frozen=True)
class EvolutionContext:
    trigger_type: TriggerType
    trigger_context: Mapping[str, Any]
    current_defense_version: str
    system_performance: Mapping[str, Any]
    pattern_spec: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PolicyGap:
    policy_type: PolicyType
    severity: GapSeverity
    confidence: float
    symptom: str
    hypothesized_cause: str
    evidence_refs: tuple[str, ...] = ()
    reasoning: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("PolicyGap confidence must be between 0 and 1")


@dataclass(frozen=True)
class DiagnosisResult:
    outcome: DiagnosisOutcome
    reason: str
    policy_gaps: tuple[PolicyGap, ...] = ()
    considered_policies: tuple[PolicyType, ...] = ()
    primary_gap_index: int | None = None

    def __post_init__(self) -> None:
        if self.outcome is DiagnosisOutcome.CHANGE_NEEDED:
            if not self.policy_gaps:
                raise ValueError("CHANGE_NEEDED requires at least one PolicyGap")
            if self.primary_gap_index is None:
                raise ValueError("CHANGE_NEEDED requires a primary_gap_index")
        if self.primary_gap_index is not None and not (
            0 <= self.primary_gap_index < len(self.policy_gaps)
        ):
            raise ValueError("primary_gap_index is out of range")

    @property
    def primary_gap(self) -> PolicyGap | None:
        if self.primary_gap_index is None:
            return None
        return self.policy_gaps[self.primary_gap_index]


@dataclass(frozen=True)
class DetectionPolicyChange:
    """One structurally safe list mutation for a Detection policy artifact."""

    path: str
    operation: ConfigListOperation
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not _SAFE_DOTTED_CONFIG_PATH.fullmatch(
            self.path
        ):
            raise ValueError("Detection policy change path must be a safe dotted path")
        if not isinstance(self.operation, ConfigListOperation):
            raise ValueError(
                "Detection policy change operation must be a ConfigListOperation"
            )
        if not isinstance(self.values, tuple) or not self.values:
            raise ValueError("Detection policy change values must be a non-empty tuple")
        if any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in self.values
        ):
            raise ValueError(
                "Detection policy change values must be non-blank, trimmed strings"
            )
        if len(self.values) != len(set(self.values)):
            raise ValueError("Detection policy change values must be unique")


@dataclass(frozen=True)
class PolicyChangeProposal:
    proposal_id: str
    target_policy: PolicyType
    base_defense_version: str
    objective: str
    requested_behavior: str
    provenance: Mapping[str, Any]
    required_signals: tuple[str, ...] = ()
    expected_impact: str = ""
    known_risks: tuple[str, ...] = ()
    base_policy_version: str | None = None
    detection_policy_changes: tuple[DetectionPolicyChange, ...] = ()


@dataclass(frozen=True)
class ArtifactBoundary:
    """Future builder sandbox boundary; enforcement belongs in concrete builders."""

    allowed_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = (
        "shared/schemas/",
        "services/evaluator/",
        "services/governance/",
        "environment/datasets/holdout/",
    )


@dataclass(frozen=True)
class ImplementationDirective:
    directive_id: str
    kind: CapabilityKind
    target_policy: PolicyType
    summary: str
    boundary: ArtifactBoundary = field(default_factory=ArtifactBoundary)
    reason: str = ""
    base_policy_version: str | None = None
    detection_policy_changes: tuple[DetectionPolicyChange, ...] = ()


@dataclass(frozen=True)
class PolicyReference:
    policy_type: PolicyType
    version: str


@dataclass(frozen=True)
class CandidatePolicy:
    target_policy: PolicyType
    policy_ref: PolicyReference
    artifact_ref: str | None = None

    def __post_init__(self) -> None:
        if self.policy_ref.policy_type is not self.target_policy:
            raise ValueError("CandidatePolicy reference must match its target policy")


@dataclass(frozen=True)
class CandidatePolicyRecord:
    """Internal lineage joining a shared CandidateResult to one policy change."""

    candidate_id: str
    build_id: str
    target_policy: PolicyType
    base_policy_version: str
    base_defense_version: str
    candidate_policy_version: str | None
    artifact_ref: str | None
    artifact_root: str | None
    build_log_ref: str | None
    build_status: str
    candidate_result: Mapping[str, Any]


@dataclass(frozen=True)
class FormalPolicyVersion:
    """Internal production policy record; shared contracts expose only its PolicyRef."""

    policy_type: PolicyType
    version: str
    candidate_id: str
    candidate_policy_version: str
    artifact_ref: str | None
    created_at: str


@dataclass(frozen=True)
class BuildOutcome:
    success: bool
    candidate_result: Mapping[str, Any]
    candidate_policy: CandidatePolicy | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.success and self.candidate_policy is None:
            raise ValueError("Successful build requires a CandidatePolicy")
        if not self.success and self.candidate_policy is not None:
            raise ValueError("Failed build cannot expose a CandidatePolicy")


@dataclass(frozen=True)
class DefenseVersionSnapshot:
    version: str
    status: str
    policies: tuple[PolicyReference, ...]
    created_at: str
    base_version: str | None = None
    candidate_id: str | None = None
    evaluation_id: str | None = None


@dataclass(frozen=True)
class EvolutionEvent:
    from_state: RunState | None
    to_state: RunState
    reason: str
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class EvolutionRun:
    run_id: str
    trigger_source: str
    current_state: RunState = RunState.RECEIVED
    target_policy: PolicyType | None = None
    proposal_ref: str | None = None
    current_candidate_ref: str | None = None
    iteration: int = 1
    retry_budget: int = 0
    history: list[EvolutionEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.iteration < 1:
            raise ValueError("iteration must be at least 1")
        if self.retry_budget < 0:
            raise ValueError("retry_budget cannot be negative")
        if not self.history:
            self.history.append(
                EvolutionEvent(None, RunState.RECEIVED, "Evolution request received")
            )


@dataclass(frozen=True)
class EvolutionExecution:
    run: EvolutionRun
    diagnosis: DiagnosisResult
    evolution_result: Mapping[str, Any]
    proposal: PolicyChangeProposal | None = None
    directive: ImplementationDirective | None = None
    candidate_result: Mapping[str, Any] | None = None
    candidate_defense_version: Mapping[str, Any] | None = None
