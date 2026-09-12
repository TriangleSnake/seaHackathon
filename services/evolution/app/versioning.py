from __future__ import annotations

from dataclasses import replace

from .domain import CandidatePolicy, DefenseVersionSnapshot, PolicyReference
from .ports import DefenseVersionRepository


class VersionManager:
    """Compose candidate snapshots; promotion and final numbering stay out of scope."""

    def __init__(self, repository: DefenseVersionRepository) -> None:
        self._repository = repository

    def read_base(self, version: str) -> DefenseVersionSnapshot:
        return self._repository.get(version)

    def compose_candidate(
        self,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy,
        candidate_id: str,
        candidate_version: str,
        created_at: str,
    ) -> DefenseVersionSnapshot:
        replacement = candidate_policy.policy_ref
        policies: list[PolicyReference] = []
        replaced = False
        for policy in base.policies:
            if policy.policy_type is candidate_policy.target_policy:
                policies.append(replacement)
                replaced = True
            else:
                policies.append(policy)
        if not replaced:
            policies.append(replacement)

        return DefenseVersionSnapshot(
            version=candidate_version,
            status="candidate",
            policies=tuple(policies),
            created_at=created_at,
            base_version=base.version,
            candidate_id=candidate_id,
        )

    def attach_evaluation(
        self, candidate: DefenseVersionSnapshot, evaluation_id: str
    ) -> DefenseVersionSnapshot:
        return replace(candidate, evaluation_id=evaluation_id)
