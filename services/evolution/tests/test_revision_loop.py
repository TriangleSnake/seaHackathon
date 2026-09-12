from __future__ import annotations

import unittest

from app.capabilities import BuilderRouter, CapabilityResolver
from app.domain import (
    CapabilityKind,
    DefenseVersionSnapshot,
    DiagnosisOutcome,
    DiagnosisResult,
    GapSeverity,
    PolicyGap,
    PolicyReference,
    PolicyType,
    RunState,
)
from app.lifecycle import VersionLifecycle
from app.orchestrator import EvolutionOrchestrator
from app.planner import PlannerResponseError
from app.repositories import InMemoryVersionRepository, VersionRepositoryError
from app.versioning import VersionManager
from tests.fakes import (
    FakeCandidateBuilder,
    FakeCandidateVersionFactory,
    FakeEvolutionPlanner,
    FakePolicyCapabilityAdapter,
)


def evolution_request() -> dict:
    return {
        "trigger": {"type": "new_spec_ready", "context": {"source": "test"}},
        "current_defense_version": {"version": "DV-001"},
        "system_performance": {"precision": 0.7, "recall": 0.4},
        "pattern_spec": {
            "pattern_id": "pattern-revision",
            "name": "Revision fixture",
            "observed_signals": [
                {"field": "message.text", "operator": "contains", "value": "fixture"}
            ],
            "current_defense_gap": "The fixture is not detected",
            "confidence": 0.9,
            "evidence_refs": ["evidence-revision"],
        },
    }


def change_diagnosis() -> DiagnosisResult:
    return DiagnosisResult(
        outcome=DiagnosisOutcome.CHANGE_NEEDED,
        reason="A deterministic revision is needed",
        policy_gaps=(
            PolicyGap(
                policy_type=PolicyType.DETECTION,
                severity=GapSeverity.HIGH,
                confidence=0.9,
                symptom="The fixture is missed",
                hypothesized_cause="The test signal is not represented",
                evidence_refs=("evidence-revision",),
                reasoning="Deterministic test diagnosis",
            ),
        ),
        considered_policies=(PolicyType.DETECTION,),
        primary_gap_index=0,
    )


def base_defense() -> DefenseVersionSnapshot:
    return DefenseVersionSnapshot(
        version="DV-001",
        status="active",
        policies=tuple(
            PolicyReference(policy, f"{policy.value}-v1") for policy in PolicyType
        ),
        created_at="2026-09-12T00:00:00+00:00",
    )


def evaluation(candidate_id: str, status: str) -> dict:
    return {
        "evaluation_id": f"evaluation-{candidate_id}",
        "candidate_id": candidate_id,
        "status": status,
        "implementation_valid": status == "passed",
        "failure_reasons": (
            ["Validation recall did not improve"] if status == "failed" else []
        ),
        "regressions": (
            ["Validation precision decreased"] if status == "failed" else []
        ),
        "baseline_metrics": {
            "precision": 0.8,
            "recall": 0.4,
            "false_positive_count": 1,
            "false_positive_rate": 0.1,
            "trigger_volume": 4,
        },
        "candidate_metrics": {
            "precision": 0.7 if status == "failed" else 0.9,
            "recall": 0.4 if status == "failed" else 0.8,
            "false_positive_count": 2 if status == "failed" else 0,
            "false_positive_rate": 0.2 if status == "failed" else 0.0,
            "trigger_volume": 5 if status == "failed" else 3,
        },
        "incremental_value": {
            "precision": -0.1 if status == "failed" else 0.1,
            "recall": 0.0 if status == "failed" else 0.4,
        },
    }


class DeterministicIds:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}-{self._counts[prefix]}"


class RevisionFailurePlanner(FakeEvolutionPlanner):
    def propose(self, run, context, diagnosis, feedback=None):
        if feedback is not None:
            raise PlannerResponseError("malformed revision output")
        return super().propose(run, context, diagnosis, feedback)


def revision_system(*, planner=None):
    planner = planner or FakeEvolutionPlanner(change_diagnosis())
    builder = FakeCandidateBuilder(
        succeeds=True, policy_version="detection-candidate"
    )
    repository = InMemoryVersionRepository([base_defense()])
    manager = VersionManager(repository)
    orchestrator = EvolutionOrchestrator(
        planner=planner,
        capability_resolver=CapabilityResolver(
            {
                PolicyType.DETECTION: FakePolicyCapabilityAdapter(
                    CapabilityKind.CONFIG
                )
            }
        ),
        builder_router=BuilderRouter({CapabilityKind.CONFIG: builder}),
        version_manager=manager,
        candidate_version_factory=FakeCandidateVersionFactory(),
        id_factory=DeterministicIds(),
        timestamp_factory=lambda: "2026-09-12T01:00:00+00:00",
    )
    return orchestrator, planner, builder, manager, repository


class EvolutionRevisionLoopTests(unittest.TestCase):
    def test_failed_validation_builds_v2_with_feedback_and_preserves_v1(self) -> None:
        runner, planner, builder, manager, repository = revision_system()
        first = runner.execute(evolution_request(), retry_budget=1)
        first_candidate = first.candidate_result["candidate_id"]
        first_version = first.candidate_defense_version["version"]
        first_proposal = first.proposal

        second = runner.handle_evaluation(
            first, evaluation(first_candidate, "failed")
        )

        self.assertEqual(second.run.current_state, RunState.VALIDATING)
        self.assertEqual(second.run.iteration, 2)
        self.assertEqual(second.run.retry_budget, 0)
        self.assertEqual(planner.proposal_calls, 2)
        self.assertEqual(len(planner.feedback_calls), 2)
        feedback = planner.feedback_calls[1]
        self.assertIsNotNone(feedback)
        assert feedback is not None and first_proposal is not None
        self.assertEqual(feedback.candidate_id, first_candidate)
        self.assertEqual(feedback.iteration, 1)
        self.assertEqual(feedback.previous_proposal, first_proposal)
        self.assertEqual(
            feedback.failure_reasons, ("Validation recall did not improve",)
        )
        self.assertEqual(feedback.baseline_metrics["precision"], 0.8)
        self.assertEqual(feedback.candidate_metrics["precision"], 0.7)
        self.assertEqual(feedback.incremental_value["precision"], -0.1)

        second_candidate = second.candidate_result["candidate_id"]
        self.assertNotEqual(first_candidate, second_candidate)
        self.assertNotEqual(first.proposal.proposal_id, second.proposal.proposal_id)
        self.assertEqual(
            second.run.candidate_history, (first_candidate, second_candidate)
        )
        self.assertEqual(len(second.run.proposal_history), 2)
        self.assertEqual(second.run.attempts[0].evaluation_status, "failed")
        self.assertEqual(second.run.attempts[0].evaluation_id, f"evaluation-{first_candidate}")
        self.assertIsNone(second.run.attempts[1].evaluation_status)

        self.assertEqual(repository.get(first_version).status, "rejected")
        self.assertEqual(
            repository.get(first_version).evaluation_id,
            f"evaluation-{first_candidate}",
        )
        records = manager.candidate_registry.list_records()
        self.assertEqual(
            tuple(record.candidate_id for record in records),
            (first_candidate, second_candidate),
        )
        self.assertEqual(len(builder.calls), 2)
        states = [event.to_state for event in second.run.history]
        revising_index = states.index(RunState.REVISING)
        self.assertEqual(
            states[revising_index : revising_index + 4],
            [
                RunState.REVISING,
                RunState.RESOLVING,
                RunState.BUILDING,
                RunState.VALIDATING,
            ],
        )

    def test_second_failure_with_exhausted_budget_is_terminal_rejected(self) -> None:
        runner, planner, _builder, _manager, repository = revision_system()
        first = runner.execute(evolution_request(), retry_budget=1)
        second = runner.handle_evaluation(
            first, evaluation(first.candidate_result["candidate_id"], "failed")
        )

        terminal = runner.handle_evaluation(
            second, evaluation(second.candidate_result["candidate_id"], "failed")
        )

        self.assertEqual(terminal.run.current_state, RunState.REJECTED)
        self.assertEqual(terminal.run.iteration, 2)
        self.assertEqual(terminal.run.retry_budget, 0)
        self.assertEqual(planner.proposal_calls, 2)
        self.assertEqual(len(terminal.run.attempts), 2)
        self.assertEqual(
            [attempt.evaluation_status for attempt in terminal.run.attempts],
            ["failed", "failed"],
        )
        for attempt in terminal.run.attempts:
            self.assertEqual(repository.get(attempt.candidate_version).status, "rejected")

    def test_passed_validation_does_not_revise_or_consume_budget(self) -> None:
        runner, planner, builder, _manager, repository = revision_system()
        first = runner.execute(evolution_request(), retry_budget=2)
        candidate_id = first.candidate_result["candidate_id"]

        passed = runner.handle_evaluation(first, evaluation(candidate_id, "passed"))

        self.assertEqual(passed.run.current_state, RunState.FROZEN)
        self.assertEqual(passed.run.iteration, 1)
        self.assertEqual(passed.run.retry_budget, 2)
        self.assertEqual(planner.proposal_calls, 1)
        self.assertEqual(len(builder.calls), 1)
        self.assertEqual(passed.run.candidate_history, (candidate_id,))
        self.assertEqual(passed.run.attempts[0].evaluation_status, "passed")
        self.assertEqual(
            repository.get(first.candidate_defense_version["version"]).status,
            "candidate",
        )

    def test_holdout_failure_is_never_returned_to_the_planner(self) -> None:
        runner, planner, _builder, manager, _repository = revision_system()
        execution = runner.execute(evolution_request(), retry_budget=2)
        lifecycle = VersionLifecycle(manager)
        lifecycle.freeze_after_validation(execution.run)
        lifecycle.begin_holdout(execution.run)

        terminal = runner.handle_evaluation(
            execution,
            evaluation(execution.candidate_result["candidate_id"], "failed"),
        )

        self.assertEqual(terminal.run.current_state, RunState.REJECTED)
        self.assertEqual(terminal.run.iteration, 1)
        self.assertEqual(terminal.run.retry_budget, 2)
        self.assertEqual(planner.proposal_calls, 1)
        self.assertEqual(planner.feedback_calls, [None])

    def test_passed_validation_then_holdout_remain_distinct_in_lineage(self) -> None:
        runner, planner, _builder, manager, _repository = revision_system()
        first = runner.execute(evolution_request(), retry_budget=2)
        candidate_id = first.candidate_result["candidate_id"]

        validated = runner.handle_evaluation(
            first, evaluation(candidate_id, "passed")
        )
        lifecycle = VersionLifecycle(manager)
        lifecycle.begin_holdout(validated.run)
        holdout_result = evaluation(candidate_id, "passed")
        holdout_result["evaluation_id"] = f"holdout-{candidate_id}"
        held = runner.handle_evaluation(validated, holdout_result)

        self.assertEqual(held.run.current_state, RunState.AWAITING_APPROVAL)
        self.assertEqual(held.run.iteration, 1)
        self.assertEqual(held.run.retry_budget, 2)
        self.assertEqual(planner.proposal_calls, 1)
        attempt = held.run.attempts[0]
        self.assertEqual(attempt.evaluation_id, f"evaluation-{candidate_id}")
        self.assertEqual(attempt.evaluation_status, "passed")
        self.assertEqual(
            attempt.holdout_evaluation_id, f"holdout-{candidate_id}"
        )
        self.assertEqual(attempt.holdout_evaluation_status, "passed")

    def test_invalid_evaluation_does_not_consume_retry_budget(self) -> None:
        runner, _planner, _builder, _manager, _repository = revision_system()
        execution = runner.execute(evolution_request(), retry_budget=1)
        invalid = evaluation("another-candidate", "failed")

        with self.assertRaisesRegex(VersionRepositoryError, "does not match"):
            runner.handle_evaluation(execution, invalid)

        self.assertEqual(execution.run.current_state, RunState.VALIDATING)
        self.assertEqual(execution.run.iteration, 1)
        self.assertEqual(execution.run.retry_budget, 1)

    def test_malformed_revision_fails_run_without_fabricating_candidate_v2(
        self,
    ) -> None:
        planner = RevisionFailurePlanner(change_diagnosis())
        runner, _planner, _builder, manager, repository = revision_system(
            planner=planner
        )
        execution = runner.execute(evolution_request(), retry_budget=1)
        candidate_id = execution.candidate_result["candidate_id"]
        candidate_version = execution.candidate_defense_version["version"]

        with self.assertRaisesRegex(
            PlannerResponseError, "malformed revision output"
        ):
            runner.handle_evaluation(
                execution, evaluation(candidate_id, "failed")
            )

        self.assertEqual(execution.run.current_state, RunState.FAILED)
        self.assertEqual(execution.run.iteration, 2)
        self.assertEqual(execution.run.retry_budget, 0)
        self.assertEqual(execution.run.candidate_history, (candidate_id,))
        self.assertEqual(len(execution.run.proposal_history), 1)
        self.assertEqual(repository.get(candidate_version).status, "rejected")
        self.assertEqual(len(manager.candidate_registry.list_records()), 1)


if __name__ == "__main__":
    unittest.main()
