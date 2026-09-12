from __future__ import annotations

import unittest
from unittest.mock import patch

from app.domain import (
    CandidatePolicy,
    DefenseVersionSnapshot,
    EvolutionRun,
    PolicyReference,
    PolicyType,
    RunState,
)
from app.lifecycle import VersionLifecycle
from app.repositories import (
    InMemoryCandidatePolicyRegistry,
    InMemoryVersionRepository,
    VersionRepositoryError,
)
from app.versioning import PromotionNotAllowed, VersionManager


CREATED = "2026-09-12T00:00:00+00:00"
PROMOTED = "2026-09-12T01:00:00+00:00"


def base_defense() -> DefenseVersionSnapshot:
    return DefenseVersionSnapshot(
        version="DV-001",
        status="active",
        policies=(
            PolicyReference(PolicyType.DETECTION, "DP-001"),
            PolicyReference(PolicyType.SCORING, "SP-001"),
            PolicyReference(PolicyType.EXPLORATION, "EP-001"),
            PolicyReference(PolicyType.INVESTIGATION, "IP-001"),
            PolicyReference(PolicyType.ASSOCIATION, "AP-001"),
        ),
        created_at=CREATED,
    )


def candidate_result(candidate_id: str, *, built: bool = True) -> dict:
    return {
        "candidate_id": candidate_id,
        "build_id": f"build-{candidate_id}",
        "base_defense_version": {"version": "DV-001"},
        "status": "built" if built else "failed",
        "changes": (
            [
                {
                    "target": "detection",
                    "operation": "modify",
                    "artifact_path": f"candidate/{candidate_id}/policy.json",
                    "summary": "Deterministic detection change",
                }
            ]
            if built
            else []
        ),
        "artifact_root": f"candidate/{candidate_id}/" if built else None,
        "build_log_ref": f"fixture://build/{candidate_id}",
    }


def evaluation(
    candidate_id: str,
    *,
    status: str = "passed",
    implementation_valid: bool = True,
    regressions: list[str] | None = None,
) -> dict:
    return {
        "evaluation_id": f"eval-{candidate_id}",
        "candidate_id": candidate_id,
        "status": status,
        "implementation_valid": implementation_valid,
        "regressions": regressions or [],
    }


class VersionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = base_defense()
        self.repository = InMemoryVersionRepository([self.base])
        self.registry = InMemoryCandidatePolicyRegistry()
        self.manager = VersionManager(self.repository, self.registry)
        self.lifecycle = VersionLifecycle(
            self.manager, timestamp_factory=lambda: PROMOTED
        )

    def build_candidate(
        self, candidate_id: str = "candidate-001", sequence: int = 1
    ) -> DefenseVersionSnapshot:
        policy = CandidatePolicy(
            target_policy=PolicyType.DETECTION,
            policy_ref=PolicyReference(PolicyType.DETECTION, f"DP-CAND-{sequence:03d}"),
            artifact_ref=f"candidate/{candidate_id}/policy.json",
        )
        result = candidate_result(candidate_id)
        self.manager.register_build(result, PolicyType.DETECTION, self.base, policy)
        return self.manager.compose_candidate(
            self.base,
            self.registry.resolve(candidate_id),
            candidate_id,
            f"DV-CAND-{sequence:03d}",
            CREATED,
        )

    @staticmethod
    def run_at(state: RunState) -> EvolutionRun:
        return EvolutionRun("run-lifecycle", "fixture", current_state=state)

    def pass_holdout(
        self, candidate: DefenseVersionSnapshot, result: dict
    ) -> EvolutionRun:
        run = self.run_at(RunState.HOLDOUT)
        self.lifecycle.record_evaluation(run, candidate.version, result)
        self.assertEqual(run.current_state, RunState.AWAITING_APPROVAL)
        return run

    def test_successful_candidate_composition_replaces_exactly_one_policy(self) -> None:
        candidate = self.build_candidate()

        self.assertEqual(candidate.status, "candidate")
        self.assertEqual(candidate.base_version, "DV-001")
        self.assertEqual(candidate.candidate_id, "candidate-001")
        policies = {item.policy_type: item.version for item in candidate.policies}
        self.assertEqual(policies[PolicyType.DETECTION], "DP-CAND-001")
        self.assertEqual(policies[PolicyType.SCORING], "SP-001")
        self.assertEqual(policies[PolicyType.EXPLORATION], "EP-001")
        self.assertEqual(policies[PolicyType.INVESTIGATION], "IP-001")
        self.assertEqual(policies[PolicyType.ASSOCIATION], "AP-001")
        self.assertEqual(self.repository.get("DV-001"), self.base)

    def test_failed_build_is_registered_without_candidate_defense(self) -> None:
        failed = candidate_result("candidate-failed", built=False)
        record = self.manager.register_build(
            failed, PolicyType.DETECTION, self.base, None
        )

        self.assertEqual(record.build_status, "failed")
        self.assertEqual(record.base_policy_version, "DP-001")
        self.assertEqual(record.build_log_ref, "fixture://build/candidate-failed")
        self.assertEqual(self.repository.list_versions(), (self.base,))

    def test_candidate_identity_cannot_consume_a_production_number(self) -> None:
        policy = CandidatePolicy(
            target_policy=PolicyType.DETECTION,
            policy_ref=PolicyReference(PolicyType.DETECTION, "DP-CAND-001"),
        )
        result = candidate_result("candidate-production-name")
        self.manager.register_build(result, PolicyType.DETECTION, self.base, policy)

        with self.assertRaisesRegex(
            VersionRepositoryError, "cannot consume a production version"
        ):
            self.manager.compose_candidate(
                self.base,
                policy,
                "candidate-production-name",
                "DV-002",
                CREATED,
            )

        self.assertEqual(self.repository.next_defense_version(), "DV-002")

    def test_candidate_policy_allocation_is_deterministic_and_reserved(self) -> None:
        expected_first = {
            PolicyType.DETECTION: "DP-CAND-001",
            PolicyType.SCORING: "SP-CAND-001",
            PolicyType.EXPLORATION: "EP-CAND-001",
            PolicyType.INVESTIGATION: "IP-CAND-001",
            PolicyType.ASSOCIATION: "AP-CAND-001",
        }

        self.assertEqual(
            {
                policy_type: self.registry.allocate_candidate_policy_version(
                    policy_type
                )
                for policy_type in PolicyType
            },
            expected_first,
        )
        self.assertEqual(
            self.registry.allocate_candidate_policy_version(PolicyType.DETECTION),
            "DP-CAND-002",
        )

    def test_manual_candidate_registration_advances_allocation(self) -> None:
        policy = CandidatePolicy(
            target_policy=PolicyType.DETECTION,
            policy_ref=PolicyReference(PolicyType.DETECTION, "DP-CAND-007"),
        )
        self.manager.register_build(
            candidate_result("candidate-manual"),
            PolicyType.DETECTION,
            self.base,
            policy,
        )

        self.assertEqual(
            self.registry.allocate_candidate_policy_version(PolicyType.DETECTION),
            "DP-CAND-008",
        )

    def test_candidate_policy_version_cannot_be_registered_twice(self) -> None:
        version = self.registry.allocate_candidate_policy_version(PolicyType.DETECTION)
        first = CandidatePolicy(
            target_policy=PolicyType.DETECTION,
            policy_ref=PolicyReference(PolicyType.DETECTION, version),
        )
        second = CandidatePolicy(
            target_policy=PolicyType.DETECTION,
            policy_ref=PolicyReference(PolicyType.DETECTION, version),
        )
        self.manager.register_build(
            candidate_result("candidate-first"),
            PolicyType.DETECTION,
            self.base,
            first,
        )

        with self.assertRaisesRegex(
            VersionRepositoryError, "Candidate policy version already registered"
        ):
            self.manager.register_build(
                candidate_result("candidate-second"),
                PolicyType.DETECTION,
                self.base,
                second,
            )

    def test_candidate_policy_identity_must_use_target_candidate_namespace(
        self,
    ) -> None:
        for invalid_version in ("SP-CAND-001", "SP-002", "candidate-policy"):
            with self.subTest(invalid_version=invalid_version):
                policy = CandidatePolicy(
                    target_policy=PolicyType.DETECTION,
                    policy_ref=PolicyReference(PolicyType.DETECTION, invalid_version),
                )
                with self.assertRaisesRegex(
                    VersionRepositoryError, "candidate namespace"
                ):
                    self.manager.register_build(
                        candidate_result(f"candidate-{invalid_version}"),
                        PolicyType.DETECTION,
                        self.base,
                        policy,
                    )

    def test_candidate_policy_allocation_does_not_consume_production_numbers(
        self,
    ) -> None:
        version = self.registry.allocate_candidate_policy_version(PolicyType.DETECTION)
        self.manager.register_build(
            candidate_result("candidate-numbering"),
            PolicyType.DETECTION,
            self.base,
            CandidatePolicy(
                target_policy=PolicyType.DETECTION,
                policy_ref=PolicyReference(PolicyType.DETECTION, version),
            ),
        )

        self.assertEqual(
            self.repository.next_policy_version(PolicyType.DETECTION), "DP-002"
        )

    def test_failed_evaluation_rejects_candidate_without_consuming_numbers(
        self,
    ) -> None:
        candidate = self.build_candidate()
        run = self.run_at(RunState.VALIDATING)

        rejected = self.lifecycle.record_evaluation(
            run,
            candidate.version,
            evaluation(candidate.candidate_id or "", status="failed"),
        )

        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(run.current_state, RunState.REJECTED)
        self.assertEqual(self.repository.current_active(), self.base)
        self.assertEqual(
            self.repository.next_policy_version(PolicyType.DETECTION), "DP-002"
        )
        self.assertEqual(self.repository.next_defense_version(), "DV-002")

    def test_failed_validation_with_retry_enters_revising_and_consumes_one_retry(
        self,
    ) -> None:
        candidate = self.build_candidate()
        run = EvolutionRun(
            "run-lifecycle-retry",
            "fixture",
            current_state=RunState.VALIDATING,
            retry_budget=2,
        )

        rejected_attempt = self.lifecycle.record_evaluation(
            run,
            candidate.version,
            evaluation(candidate.candidate_id or "", status="failed"),
        )

        self.assertEqual(rejected_attempt.status, "rejected")
        self.assertEqual(run.current_state, RunState.REVISING)
        self.assertEqual(run.iteration, 2)
        self.assertEqual(run.retry_budget, 1)
        event = run.history[-1]
        self.assertEqual(event.details["failed_iteration"], 1)
        self.assertEqual(event.details["next_iteration"], 2)
        self.assertEqual(event.details["retry_budget_remaining"], 1)

    def test_needs_review_keeps_candidate_unpromoted_and_active_unchanged(self) -> None:
        candidate = self.build_candidate()
        result = evaluation(candidate.candidate_id or "")
        run = self.pass_holdout(candidate, result)

        promoted = self.lifecycle.apply_governance(
            run, candidate.version, result, {"decision": "needs_review"}
        )

        self.assertIsNone(promoted)
        self.assertEqual(run.current_state, RunState.AWAITING_APPROVAL)
        self.assertEqual(self.repository.current_active(), self.base)
        self.assertEqual(self.repository.next_defense_version(), "DV-002")

    def test_governance_reject_marks_candidate_rejected_without_numbering(self) -> None:
        candidate = self.build_candidate()
        result = evaluation(candidate.candidate_id or "")
        run = self.pass_holdout(candidate, result)

        rejected = self.lifecycle.apply_governance(
            run, candidate.version, result, {"decision": "reject"}
        )

        self.assertIsNotNone(rejected)
        self.assertEqual(self.repository.get(candidate.version).status, "rejected")
        self.assertEqual(run.current_state, RunState.REJECTED)
        self.assertEqual(
            self.repository.next_policy_version(PolicyType.DETECTION), "DP-002"
        )
        self.assertEqual(self.repository.next_defense_version(), "DV-002")

    def test_approval_promotes_policy_and_complete_defense_together(self) -> None:
        candidate = self.build_candidate()
        result = evaluation(candidate.candidate_id or "")
        run = self.pass_holdout(candidate, result)

        promoted = self.lifecycle.apply_governance(
            run, candidate.version, result, {"decision": "approve"}
        )

        self.assertIsNotNone(promoted)
        assert promoted is not None
        self.assertEqual(promoted.version, "DV-002")
        self.assertEqual(promoted.status, "approved")
        policies = {item.policy_type: item.version for item in promoted.policies}
        self.assertEqual(policies[PolicyType.DETECTION], "DP-002")
        self.assertEqual(policies[PolicyType.SCORING], "SP-001")
        self.assertEqual(
            self.repository.get_policy("DP-002").candidate_id, "candidate-001"
        )
        self.assertEqual(self.repository.get(candidate.version).status, "candidate")
        self.assertEqual(self.repository.current_active(), self.base)
        self.assertEqual(run.current_state, RunState.APPROVED)

    def test_activation_retires_previous_active_and_activates_approved(self) -> None:
        candidate = self.build_candidate()
        result = evaluation(candidate.candidate_id or "")
        run = self.pass_holdout(candidate, result)
        promoted = self.lifecycle.apply_governance(
            run, candidate.version, result, {"decision": "approve"}
        )
        assert promoted is not None

        active = self.lifecycle.activate(run, promoted.version)

        self.assertEqual(active.status, "active")
        self.assertEqual(self.repository.get("DV-001").status, "retired")
        self.assertEqual(self.repository.current_active(), active)
        self.assertEqual(
            sum(item.status == "active" for item in self.repository.list_versions()), 1
        )
        history = self.repository.history()
        self.assertTrue(
            any(
                item.version == "DV-001" and item.status == "active" for item in history
            )
        )
        self.assertTrue(
            any(
                item.version == "DV-001" and item.status == "retired"
                for item in history
            )
        )
        self.assertTrue(
            any(
                item.version == "DV-002" and item.status == "approved"
                for item in history
            )
        )
        self.assertEqual(run.current_state, RunState.ACTIVE)

    def test_all_policy_types_use_deterministic_production_prefixes(self) -> None:
        expected = {
            PolicyType.DETECTION: "DP-002",
            PolicyType.SCORING: "SP-002",
            PolicyType.EXPLORATION: "EP-002",
            PolicyType.INVESTIGATION: "IP-002",
            PolicyType.ASSOCIATION: "AP-002",
        }
        self.assertEqual(
            {
                policy_type: self.repository.next_policy_version(policy_type)
                for policy_type in PolicyType
            },
            expected,
        )

    def test_failed_and_rejected_candidates_do_not_create_numbering_gaps(self) -> None:
        self.manager.register_build(
            candidate_result("candidate-a", built=False),
            PolicyType.DETECTION,
            self.base,
            None,
        )
        rejected_candidate = self.build_candidate("candidate-b", sequence=2)
        rejected_evaluation = evaluation("candidate-b")
        rejected_run = self.pass_holdout(rejected_candidate, rejected_evaluation)
        self.lifecycle.apply_governance(
            rejected_run,
            rejected_candidate.version,
            rejected_evaluation,
            {"decision": "reject"},
        )

        approved_candidate = self.build_candidate("candidate-c", sequence=3)
        approved_evaluation = evaluation("candidate-c")
        approved_run = self.pass_holdout(approved_candidate, approved_evaluation)
        promoted = self.lifecycle.apply_governance(
            approved_run,
            approved_candidate.version,
            approved_evaluation,
            {"decision": "approve"},
        )

        assert promoted is not None
        self.assertEqual(promoted.version, "DV-002")
        self.assertEqual(self.repository.get_policy("DP-002").version, "DP-002")

    def test_passed_evaluation_with_regressions_cannot_be_promoted(self) -> None:
        candidate = self.build_candidate()
        result = evaluation(
            candidate.candidate_id or "", regressions=["precision decreased"]
        )
        run = self.pass_holdout(candidate, result)

        with self.assertRaisesRegex(PromotionNotAllowed, "no reported regressions"):
            self.lifecycle.apply_governance(
                run, candidate.version, result, {"decision": "approve"}
            )

        self.assertEqual(run.current_state, RunState.AWAITING_APPROVAL)
        self.assertEqual(self.repository.current_active(), self.base)
        self.assertEqual(self.repository.next_defense_version(), "DV-002")

    def test_activation_failure_preserves_current_active_and_approved_version(
        self,
    ) -> None:
        candidate = self.build_candidate()
        result = evaluation(candidate.candidate_id or "")
        run = self.pass_holdout(candidate, result)
        promoted = self.lifecycle.apply_governance(
            run, candidate.version, result, {"decision": "approve"}
        )
        assert promoted is not None

        with patch.object(
            self.repository, "activate", side_effect=RuntimeError("fixture outage")
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture outage"):
                self.lifecycle.activate(run, promoted.version)

        self.assertEqual(self.repository.current_active(), self.base)
        self.assertEqual(self.repository.get(promoted.version).status, "approved")
        self.assertEqual(self.repository.get(candidate.version).status, "candidate")
        self.assertEqual(run.current_state, RunState.FAILED)


if __name__ == "__main__":
    unittest.main()
