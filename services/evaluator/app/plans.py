from __future__ import annotations

from typing import Any, Protocol

from .errors import EvaluationPlanError
from .models import EvaluationPlan, PolicyType


class VersionManagerView(Protocol):
    @property
    def candidate_registry(self) -> Any: ...

    def read_base(self, version: str) -> Any: ...


class RegisteredCandidateEvaluationPlanResolver:
    """Resolve one registered Detection candidate against its exact base policy."""

    def __init__(self, versions: VersionManagerView) -> None:
        self._versions = versions

    def resolve(
        self, candidate_id: str, baseline_defense_version: str
    ) -> EvaluationPlan:
        try:
            base = self._versions.read_base(baseline_defense_version)
            candidate = self._versions.candidate_registry.resolve(candidate_id)
        except (KeyError, LookupError, ValueError) as exc:
            raise EvaluationPlanError(
                "Evaluation candidate or baseline defense could not be resolved"
            ) from exc

        base_detection = tuple(
            reference
            for reference in base.policies
            if getattr(reference.policy_type, "value", reference.policy_type)
            == PolicyType.DETECTION.value
        )
        candidate_type = getattr(
            candidate.target_policy, "value", candidate.target_policy
        )
        if len(base_detection) != 1 or candidate_type != PolicyType.DETECTION.value:
            raise EvaluationPlanError(
                "The concrete demo resolver supports exactly one Detection policy"
            )
        candidate_ref_type = getattr(
            candidate.policy_ref.policy_type,
            "value",
            candidate.policy_ref.policy_type,
        )
        if candidate_ref_type != PolicyType.DETECTION.value:
            raise EvaluationPlanError(
                "Candidate policy reference does not target Detection"
            )
        return EvaluationPlan(
            policy_type=PolicyType.DETECTION,
            baseline_defense_version=base.version,
            baseline_policy_ref=base_detection[0].version,
            candidate_policy_ref=candidate.policy_ref.version,
        )
