from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .domain import (
    CandidatePolicy,
    CodeCandidate,
    CandidatePolicyRecord,
    DefenseVersionSnapshot,
    FormalPolicyVersion,
    PolicyReference,
    PolicyType,
)
from .ports import CandidatePolicyRegistry, DefenseVersionRepository
from .repositories import InMemoryCandidatePolicyRegistry, VersionRepositoryError


class PromotionNotAllowed(VersionRepositoryError):
    pass


class VersionManager:
    """Own candidate composition, formal promotion, and repository activation."""

    def __init__(
        self,
        repository: DefenseVersionRepository,
        candidate_registry: CandidatePolicyRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._candidates = candidate_registry or InMemoryCandidatePolicyRegistry()

    @property
    def repository(self) -> DefenseVersionRepository:
        return self._repository

    @property
    def candidate_registry(self) -> CandidatePolicyRegistry:
        return self._candidates

    def read_base(self, version: str) -> DefenseVersionSnapshot:
        return self._repository.get(version)

    def register_build(
        self,
        candidate_result: Mapping[str, Any],
        target_policy: PolicyType,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy | None,
        code_candidate: CodeCandidate | None = None,
    ) -> CandidatePolicyRecord:
        return self._candidates.register(
            candidate_result, target_policy, base, candidate_policy, code_candidate
        )

    def compose_candidate(
        self,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy,
        candidate_id: str,
        candidate_version: str,
        created_at: str,
    ) -> DefenseVersionSnapshot:
        record = self._candidates.get(candidate_id)
        if record.build_status != "built":
            raise VersionRepositoryError(
                "A failed build cannot create a candidate defense"
            )
        registered = self._candidates.resolve(candidate_id)
        if registered != candidate_policy:
            raise VersionRepositoryError(
                "CandidatePolicy does not match its registry record"
            )
        if record.base_defense_version != base.version:
            raise VersionRepositoryError(
                "Candidate registry base does not match composition base"
            )

        target_indexes = [
            index
            for index, policy in enumerate(base.policies)
            if policy.policy_type is candidate_policy.target_policy
        ]
        if len(target_indexes) != 1:
            raise VersionRepositoryError(
                "Candidate composition must replace exactly one base PolicyRef"
            )
        policies = list(base.policies)
        policies[target_indexes[0]] = candidate_policy.policy_ref

        snapshot = DefenseVersionSnapshot(
            version=candidate_version,
            status="candidate",
            policies=tuple(policies),
            created_at=created_at,
            base_version=base.version,
            candidate_id=candidate_id,
        )
        self._repository.save_candidate(snapshot)
        return snapshot

    def record_evaluation(
        self,
        candidate_version: str,
        evaluation: Mapping[str, Any],
    ) -> DefenseVersionSnapshot:
        candidate = self._repository.get(candidate_version)
        if candidate.status != "candidate" or not candidate.candidate_id:
            raise VersionRepositoryError("Evaluation requires a candidate defense")
        evaluation_id = _required_string(evaluation, "evaluation_id")
        if _required_string(evaluation, "candidate_id") != candidate.candidate_id:
            raise VersionRepositoryError(
                "Evaluation candidate does not match defense candidate"
            )
        status = _required_string(evaluation, "status")
        if status not in {"passed", "failed"}:
            raise VersionRepositoryError(f"Unsupported evaluation status: {status}")
        return self._repository.link_evaluation(
            candidate_version,
            evaluation_id,
            rejected=status == "failed",
        )

    def apply_governance(
        self,
        candidate_version: str,
        evaluation: Mapping[str, Any],
        decision: str,
        created_at: str,
    ) -> DefenseVersionSnapshot | None:
        if decision == "needs_review":
            return None
        if decision == "reject":
            return self._repository.reject_candidate(candidate_version)
        if decision != "approve":
            raise VersionRepositoryError(f"Unsupported governance decision: {decision}")
        return self._promote(candidate_version, evaluation, created_at)

    def activate(self, formal_defense_version: str) -> DefenseVersionSnapshot:
        return self._repository.activate(formal_defense_version)

    def _promote(
        self,
        candidate_version: str,
        evaluation: Mapping[str, Any],
        created_at: str,
    ) -> DefenseVersionSnapshot:
        candidate = self._repository.get(candidate_version)
        if candidate.status != "candidate" or not candidate.candidate_id:
            raise PromotionNotAllowed("Only an unrejected candidate can be promoted")
        evaluation_id = _required_string(evaluation, "evaluation_id")
        if candidate.evaluation_id != evaluation_id:
            raise PromotionNotAllowed("Promotion requires the linked evaluation")
        if _required_string(evaluation, "candidate_id") != candidate.candidate_id:
            raise PromotionNotAllowed(
                "Evaluation candidate does not match promotion candidate"
            )
        if evaluation.get("status") != "passed":
            raise PromotionNotAllowed("Promotion requires a passed evaluation")
        if evaluation.get("implementation_valid") is not True:
            raise PromotionNotAllowed("Promotion requires a valid implementation")
        regressions = evaluation.get("regressions", [])
        if not isinstance(regressions, list) or regressions:
            raise PromotionNotAllowed("Promotion requires no reported regressions")

        record = self._candidates.get(candidate.candidate_id)
        candidate_policy = self._candidates.resolve(candidate.candidate_id)
        formal_policy_version = self._repository.next_policy_version(
            candidate_policy.target_policy
        )
        formal_policy = FormalPolicyVersion(
            policy_type=candidate_policy.target_policy,
            version=formal_policy_version,
            candidate_id=candidate.candidate_id,
            candidate_policy_version=candidate_policy.policy_ref.version,
            artifact_ref=record.artifact_ref,
            created_at=created_at,
        )

        policies = tuple(
            (
                PolicyReference(policy.policy_type, formal_policy_version)
                if policy.policy_type is candidate_policy.target_policy
                else policy
            )
            for policy in candidate.policies
        )
        formal_defense = DefenseVersionSnapshot(
            version=self._repository.next_defense_version(),
            status="approved",
            policies=policies,
            created_at=created_at,
            base_version=candidate.base_version,
            candidate_id=candidate.candidate_id,
            evaluation_id=evaluation_id,
        )
        self._repository.save_promotion(formal_policy, formal_defense)
        return formal_defense


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise VersionRepositoryError(f"{key} must be a non-empty string")
    return value
