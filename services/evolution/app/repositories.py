from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import re
from threading import Lock
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .domain import (
    CandidatePolicy,
    CodeCandidate,
    CandidatePolicyRecord,
    DefenseVersionSnapshot,
    FormalPolicyVersion,
    PolicyReference,
    PolicyType,
)


class VersionRepositoryError(ValueError):
    pass


_POLICY_PREFIX = {
    PolicyType.DETECTION: "DP",
    PolicyType.SCORING: "SP",
    PolicyType.EXPLORATION: "EP",
    PolicyType.INVESTIGATION: "IP",
    PolicyType.ASSOCIATION: "AP",
}


class InMemoryCandidatePolicyRegistry:
    """Process-local build lineage; CandidateResult remains the shared artifact."""

    def __init__(self) -> None:
        self._records: dict[str, CandidatePolicyRecord] = {}
        self._reserved_versions: set[str] = set()
        self._lock = Lock()

    def allocate_candidate_policy_version(self, policy_type: PolicyType) -> str:
        prefix = f"{_POLICY_PREFIX[policy_type]}-CAND"
        pattern = re.compile(rf"^{prefix}-(\d+)$")
        with self._lock:
            versions = set(self._reserved_versions)
            versions.update(
                record.candidate_policy_version
                for record in self._records.values()
                if record.candidate_policy_version is not None
            )
            version = _next_version(prefix, pattern, versions)
            self._reserved_versions.add(version)
            return version

    def has_build(self, build_id: str) -> bool:
        with self._lock:
            return any(record.build_id == build_id for record in self._records.values())

    def register(
        self,
        candidate_result: Mapping[str, Any],
        target_policy: PolicyType,
        base: DefenseVersionSnapshot,
        candidate_policy: CandidatePolicy | None,
        code_candidate: CodeCandidate | None = None,
    ) -> CandidatePolicyRecord:
        candidate_id = _required_string(candidate_result, "candidate_id")
        build_id = _required_string(candidate_result, "build_id")
        status = _required_string(candidate_result, "status")
        if status not in {"built", "failed"}:
            raise VersionRepositoryError(
                f"Unsupported candidate build status: {status}"
            )
        with self._lock:
            self._assert_registration_available(candidate_id, candidate_policy)

        base_ref = candidate_result.get("base_defense_version")
        if not isinstance(base_ref, Mapping) or base_ref.get("version") != base.version:
            raise VersionRepositoryError(
                "CandidateResult base defense does not match repository base"
            )

        matching_base = tuple(
            policy for policy in base.policies if policy.policy_type is target_policy
        )
        if len(matching_base) != 1:
            raise VersionRepositoryError(
                "Base defense must contain exactly one reference for the target policy"
            )

        if status == "built" and (candidate_policy is None) == (code_candidate is None):
            raise VersionRepositoryError(
                "A built candidate requires an internal CandidatePolicy"
            )
        if status == "failed" and (candidate_policy is not None or code_candidate is not None):
            raise VersionRepositoryError(
                "A failed candidate cannot register a CandidatePolicy"
            )
        if (
            candidate_policy is not None
            and candidate_policy.target_policy is not target_policy
        ):
            raise VersionRepositoryError(
                "CandidatePolicy target does not match the proposal"
            )

        changes = candidate_result.get("changes")
        if not isinstance(changes, list):
            raise VersionRepositoryError("CandidateResult changes must be a list")
        changed_targets = {
            str(change.get("target"))
            for change in changes
            if isinstance(change, Mapping)
        }
        if status == "built" and changed_targets != {target_policy.value}:
            raise VersionRepositoryError(
                "One EvolutionRun may change exactly one target policy"
            )

        if candidate_policy is not None:
            formal_pattern = re.compile(rf"^{_POLICY_PREFIX[target_policy]}-(\d+)$")
            if formal_pattern.fullmatch(candidate_policy.policy_ref.version):
                raise VersionRepositoryError(
                    "Candidate policy identity cannot consume a production version"
                )
            candidate_pattern = re.compile(
                rf"^{_POLICY_PREFIX[target_policy]}-CAND-"
                r"[A-Za-z0-9][A-Za-z0-9._-]*$"
            )
            if not candidate_pattern.fullmatch(candidate_policy.policy_ref.version):
                raise VersionRepositoryError(
                    "Candidate policy identity must use the target policy's "
                    f"candidate namespace: {_POLICY_PREFIX[target_policy]}-CAND-*"
                )

        frozen_result = _deep_freeze(deepcopy(dict(candidate_result)))
        if code_candidate and code_candidate.candidate_id != candidate_id:
            raise VersionRepositoryError("Code candidate identity mismatch")
        record = CandidatePolicyRecord(
            candidate_id=candidate_id,
            build_id=build_id,
            target_policy=target_policy,
            base_policy_version=matching_base[0].version,
            base_defense_version=base.version,
            candidate_policy_version=(
                candidate_policy.policy_ref.version if candidate_policy else None
            ),
            artifact_ref=candidate_policy.artifact_ref if candidate_policy else None,
            artifact_root=_optional_string(candidate_result.get("artifact_root")),
            build_log_ref=_optional_string(candidate_result.get("build_log_ref")),
            build_status=status,
            candidate_result=frozen_result,
            code_candidate=code_candidate,
        )
        with self._lock:
            self._assert_registration_available(candidate_id, candidate_policy)
            self._records[candidate_id] = record
            if candidate_policy is not None:
                self._reserved_versions.discard(candidate_policy.policy_ref.version)
        return record

    def _assert_registration_available(
        self, candidate_id: str, candidate_policy: CandidatePolicy | None
    ) -> None:
        if candidate_id in self._records:
            raise VersionRepositoryError(
                f"Candidate already registered: {candidate_id}"
            )
        if candidate_policy is not None and any(
            existing.candidate_policy_version == candidate_policy.policy_ref.version
            for existing in self._records.values()
        ):
            raise VersionRepositoryError(
                "Candidate policy version already registered: "
                f"{candidate_policy.policy_ref.version}"
            )

    def get(self, candidate_id: str) -> CandidatePolicyRecord:
        with self._lock:
            return self._records[candidate_id]

    def resolve(self, candidate_id: str) -> CandidatePolicy:
        record = self.get(candidate_id)
        if record.build_status != "built" or record.candidate_policy_version is None:
            raise VersionRepositoryError(
                f"Candidate has no built policy: {candidate_id}"
            )
        return CandidatePolicy(
            target_policy=record.target_policy,
            policy_ref=PolicyReference(
                record.target_policy, record.candidate_policy_version
            ),
            artifact_ref=record.artifact_ref,
        )

    def list_records(self) -> tuple[CandidatePolicyRecord, ...]:
        with self._lock:
            return tuple(self._records.values())


class InMemoryVersionRepository:
    """Append-oriented defense history and atomic in-memory promotion/activation."""

    def __init__(
        self,
        versions: Iterable[DefenseVersionSnapshot] = (),
        policies: Iterable[FormalPolicyVersion] = (),
    ) -> None:
        self._versions: dict[str, DefenseVersionSnapshot] = {}
        self._history: list[DefenseVersionSnapshot] = []
        self._policies: dict[str, FormalPolicyVersion] = {}
        self._lock = Lock()
        for snapshot in versions:
            if snapshot.version in self._versions:
                raise VersionRepositoryError(
                    f"Duplicate defense version: {snapshot.version}"
                )
            self._versions[snapshot.version] = snapshot
            self._history.append(snapshot)
        for policy in policies:
            if policy.version in self._policies:
                raise VersionRepositoryError(
                    f"Duplicate policy version: {policy.version}"
                )
            self._policies[policy.version] = policy
        self._assert_single_active(self._versions.values())

    def get(self, version: str) -> DefenseVersionSnapshot:
        with self._lock:
            return self._versions[version]

    def save_candidate(self, snapshot: DefenseVersionSnapshot) -> None:
        if snapshot.status != "candidate" or not snapshot.candidate_id:
            raise VersionRepositoryError(
                "Candidate snapshot must have candidate status and id"
            )
        if re.fullmatch(r"DV-\d+", snapshot.version):
            raise VersionRepositoryError(
                "Candidate defense identity cannot consume a production version"
            )
        with self._lock:
            if snapshot.version in self._versions:
                raise VersionRepositoryError(
                    f"Defense version already exists: {snapshot.version}"
                )
            self._versions[snapshot.version] = snapshot
            self._history.append(snapshot)

    def link_evaluation(
        self, version: str, evaluation_id: str, *, rejected: bool
    ) -> DefenseVersionSnapshot:
        with self._lock:
            current = self._versions[version]
            if current.status != "candidate":
                raise VersionRepositoryError(
                    "Only a candidate can receive an evaluation"
                )
            updated = replace(
                current,
                evaluation_id=evaluation_id,
                status="rejected" if rejected else "candidate",
            )
            self._versions[version] = updated
            self._history.append(updated)
            return updated

    def reject_candidate(self, version: str) -> DefenseVersionSnapshot:
        with self._lock:
            current = self._versions[version]
            if current.status == "rejected":
                return current
            if current.status != "candidate":
                raise VersionRepositoryError("Only a candidate can be rejected")
            updated = replace(current, status="rejected")
            self._versions[version] = updated
            self._history.append(updated)
            return updated

    def next_policy_version(self, policy_type: PolicyType) -> str:
        prefix = _POLICY_PREFIX[policy_type]
        pattern = re.compile(rf"^{prefix}-(\d+)$")
        with self._lock:
            versions = set(self._policies)
            versions.update(
                policy.version
                for defense in self._versions.values()
                for policy in defense.policies
                if policy.policy_type is policy_type
            )
            return _next_version(prefix, pattern, versions)

    def next_defense_version(self) -> str:
        pattern = re.compile(r"^DV-(\d+)$")
        with self._lock:
            return _next_version("DV", pattern, self._versions)

    def save_promotion(
        self,
        policy: FormalPolicyVersion,
        defense: DefenseVersionSnapshot,
    ) -> None:
        if defense.status != "approved":
            raise VersionRepositoryError("A promoted defense must start approved")
        if PolicyReference(policy.policy_type, policy.version) not in defense.policies:
            raise VersionRepositoryError(
                "Promoted defense does not reference promoted policy"
            )
        if not defense.candidate_id or policy.candidate_id != defense.candidate_id:
            raise VersionRepositoryError(
                "Promoted policy and defense must share candidate lineage"
            )
        with self._lock:
            if any(
                existing.candidate_id == policy.candidate_id
                for existing in self._policies.values()
            ):
                raise VersionRepositoryError(
                    f"Candidate is already promoted: {policy.candidate_id}"
                )
            if policy.version in self._policies:
                raise VersionRepositoryError(
                    f"Policy version already exists: {policy.version}"
                )
            if defense.version in self._versions:
                raise VersionRepositoryError(
                    f"Defense version already exists: {defense.version}"
                )
            # Both records become visible together while holding the repository lock.
            self._policies[policy.version] = policy
            self._versions[defense.version] = defense
            self._history.append(defense)

    def activate(self, version: str) -> DefenseVersionSnapshot:
        with self._lock:
            target = self._versions[version]
            if target.status != "approved":
                raise VersionRepositoryError(
                    "Only an approved defense can be activated"
                )
            active = [
                item for item in self._versions.values() if item.status == "active"
            ]
            self._assert_single_active(active)

            retired = replace(active[0], status="retired") if active else None
            activated = replace(target, status="active")
            # All validation and object construction occurs before repository mutation.
            if retired is not None:
                self._versions[retired.version] = retired
                self._history.append(retired)
            self._versions[version] = activated
            self._history.append(activated)
            return activated

    def current_active(self) -> DefenseVersionSnapshot | None:
        with self._lock:
            active = [
                item for item in self._versions.values() if item.status == "active"
            ]
            self._assert_single_active(active)
            return active[0] if active else None

    def list_versions(self) -> tuple[DefenseVersionSnapshot, ...]:
        with self._lock:
            return tuple(self._versions.values())

    def history(self) -> tuple[DefenseVersionSnapshot, ...]:
        with self._lock:
            return tuple(self._history)

    def get_policy(self, version: str) -> FormalPolicyVersion:
        with self._lock:
            return self._policies[version]

    def list_policies(self) -> tuple[FormalPolicyVersion, ...]:
        with self._lock:
            return tuple(self._policies.values())

    @staticmethod
    def _assert_single_active(versions: Iterable[DefenseVersionSnapshot]) -> None:
        if sum(item.status == "active" for item in versions) > 1:
            raise VersionRepositoryError(
                "Repository cannot contain multiple active defenses"
            )


def _next_version(
    prefix: str, pattern: re.Pattern[str], versions: Iterable[str]
) -> str:
    used = [
        int(match.group(1)) for value in versions if (match := pattern.fullmatch(value))
    ]
    return f"{prefix}-{max(used, default=0) + 1:03d}"


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise VersionRepositoryError(
            f"CandidateResult {key} must be a non-empty string"
        )
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise VersionRepositoryError(
            "Optional candidate references must be strings or null"
        )
    return value


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value
