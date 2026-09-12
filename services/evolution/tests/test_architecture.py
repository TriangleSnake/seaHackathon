from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest

from app.adapters import SharedContractAdapter
from app.capabilities import BuilderRouter, CapabilityResolver
from app.domain import (
    CapabilityKind,
    DefenseVersionSnapshot,
    DiagnosisOutcome,
    DiagnosisResult,
    EvolutionRun,
    GapSeverity,
    PolicyGap,
    PolicyReference,
    PolicyType,
    RunState,
)
from app.orchestrator import EvolutionOrchestrator
from app.state_machine import EvolutionStateMachine, InvalidStateTransition
from app.versioning import VersionManager
from tests.fakes import (
    FakeCandidateBuilder,
    FakeCandidateVersionFactory,
    FakeDefenseVersionRepository,
    FakeEvolutionPlanner,
    FakePolicyCapabilityAdapter,
)


def request(trigger: str = "new_spec_ready", *, include_pattern: bool = True) -> dict:
    payload = {
        "trigger": {"type": trigger, "context": {"source": "test"}},
        "current_defense_version": {"version": "v1"},
        "system_performance": {"precision": 0.7},
    }
    if include_pattern:
        payload["pattern_spec"] = {
            "pattern_id": "pattern-1",
            "name": "Test pattern",
            "observed_signals": [
                {"field": "activity_score", "operator": "gte", "value": 0.8}
            ],
            "current_defense_gap": "Current policy misses this test fixture",
            "confidence": 0.9,
            "evidence_refs": ["evidence-1"],
        }
    return payload


def gap(policy: PolicyType = PolicyType.DETECTION) -> PolicyGap:
    return PolicyGap(
        policy_type=policy,
        severity=GapSeverity.HIGH,
        confidence=0.9,
        symptom="Known fixture is missed",
        hypothesized_cause="Signal is not represented",
        evidence_refs=("evidence-1",),
        reasoning="Test-only diagnosis",
    )


def base_version() -> DefenseVersionSnapshot:
    return DefenseVersionSnapshot(
        version="v1",
        status="active",
        policies=tuple(
            PolicyReference(policy, f"{policy.value}-v1") for policy in PolicyType
        ),
        created_at="2026-09-12T00:00:00+00:00",
    )


class DeterministicIds:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self.counts[prefix] = self.counts.get(prefix, 0) + 1
        return f"{prefix}-{self.counts[prefix]}"


def orchestrator(
    diagnosis: DiagnosisResult,
    *,
    capability: CapabilityKind = CapabilityKind.CONFIG,
    builder_succeeds: bool = True,
) -> tuple[EvolutionOrchestrator, FakeEvolutionPlanner, FakeCandidateBuilder]:
    planner = FakeEvolutionPlanner(diagnosis)
    builder = FakeCandidateBuilder(
        succeeds=builder_succeeds, policy_version="detection-v2"
    )
    resolver = CapabilityResolver(
        {policy: FakePolicyCapabilityAdapter(capability) for policy in PolicyType}
    )
    runner = EvolutionOrchestrator(
        planner,
        resolver,
        BuilderRouter(
            {
                CapabilityKind.CONFIG: builder,
                CapabilityKind.CODE: builder,
            }
        ),
        VersionManager(FakeDefenseVersionRepository([base_version()])),
        FakeCandidateVersionFactory(),
        id_factory=DeterministicIds(),
        timestamp_factory=lambda: "2026-09-12T01:00:00+00:00",
    )
    return runner, planner, builder


class EvolutionArchitectureTests(unittest.TestCase):
    def test_each_trigger_enters_the_same_diagnosis_pipeline(self) -> None:
        diagnosis = DiagnosisResult(DiagnosisOutcome.NO_ACTION, "Nothing to change")
        for trigger in (
            "new_spec_ready",
            "performance_degradation",
            "recurring",
        ):
            with self.subTest(trigger=trigger):
                runner, _, _ = orchestrator(diagnosis)
                execution = runner.execute(request(trigger))
                self.assertEqual(execution.run.trigger_source, trigger)
                self.assertEqual(execution.run.history[1].to_state, RunState.DIAGNOSING)

    def test_no_action_terminates_cleanly(self) -> None:
        diagnosis = DiagnosisResult(DiagnosisOutcome.NO_ACTION, "No material gap")
        runner, planner, builder = orchestrator(diagnosis)
        execution = runner.execute(request())
        self.assertEqual(execution.run.current_state, RunState.NO_ACTION)
        self.assertEqual(execution.evolution_result["action"], "no_change")
        self.assertEqual(planner.proposal_calls, 0)
        self.assertEqual(builder.calls, [])

    def test_diagnosis_creates_exactly_one_primary_policy_proposal(self) -> None:
        diagnosis = DiagnosisResult(
            DiagnosisOutcome.CHANGE_NEEDED,
            "Two gaps considered; detection is primary",
            policy_gaps=(gap(PolicyType.DETECTION), gap(PolicyType.SCORING)),
            considered_policies=tuple(PolicyType),
            primary_gap_index=0,
        )
        runner, planner, builder = orchestrator(diagnosis)
        execution = runner.execute(request())
        self.assertEqual(planner.proposal_calls, 1)
        self.assertEqual(execution.run.target_policy, PolicyType.DETECTION)
        self.assertEqual(
            execution.evolution_result["target_policies"], ["detection"]
        )
        self.assertEqual(builder.calls[0]["target_policies"], ["detection"])
        proposed_event = next(
            event for event in execution.run.history if event.to_state is RunState.PROPOSED
        )
        self.assertEqual(proposed_event.details["unselected_gap_count"], 1)

    def test_resolver_routes_config_code_and_unsupported(self) -> None:
        diagnosis = DiagnosisResult(
            DiagnosisOutcome.CHANGE_NEEDED,
            "Change",
            policy_gaps=(gap(),),
            primary_gap_index=0,
        )
        _, planner, _ = orchestrator(diagnosis)
        context = SharedContractAdapter().evolution_context(request())
        run = EvolutionRun("run-test", "new_spec_ready")
        proposal = planner.propose(run, context, diagnosis)
        for kind in (CapabilityKind.CONFIG, CapabilityKind.CODE, CapabilityKind.UNSUPPORTED):
            with self.subTest(kind=kind):
                resolver = CapabilityResolver(
                    {PolicyType.DETECTION: FakePolicyCapabilityAdapter(kind)}
                )
                self.assertEqual(resolver.resolve(proposal).kind, kind)

        missing = CapabilityResolver({}).resolve(proposal)
        self.assertEqual(missing.kind, CapabilityKind.UNSUPPORTED)

    def test_one_core_resolver_supports_all_five_policy_types(self) -> None:
        diagnosis = DiagnosisResult(
            DiagnosisOutcome.CHANGE_NEEDED,
            "Change",
            policy_gaps=(gap(),),
            primary_gap_index=0,
        )
        _, planner, _ = orchestrator(diagnosis)
        context = SharedContractAdapter().evolution_context(request())
        proposal = planner.propose(
            EvolutionRun("run-test", "new_spec_ready"), context, diagnosis
        )
        resolver = CapabilityResolver(
            {
                policy: FakePolicyCapabilityAdapter(CapabilityKind.CONFIG)
                for policy in PolicyType
            }
        )
        for policy in PolicyType:
            with self.subTest(policy=policy):
                directive = resolver.resolve(
                    replace(proposal, target_policy=policy)
                )
                self.assertEqual(directive.target_policy, policy)

    def test_builder_failure_does_not_create_candidate_defense_version(self) -> None:
        diagnosis = DiagnosisResult(
            DiagnosisOutcome.CHANGE_NEEDED,
            "Build this",
            policy_gaps=(gap(),),
            primary_gap_index=0,
        )
        runner, _, _ = orchestrator(diagnosis, builder_succeeds=False)
        execution = runner.execute(request())
        self.assertEqual(execution.run.current_state, RunState.FAILED)
        candidate_result = execution.candidate_result
        self.assertIsNotNone(candidate_result)
        assert candidate_result is not None
        self.assertEqual(candidate_result["status"], "failed")
        self.assertIsNone(execution.candidate_defense_version)

    def test_successful_build_composes_one_policy_into_candidate_version(self) -> None:
        diagnosis = DiagnosisResult(
            DiagnosisOutcome.CHANGE_NEEDED,
            "Build this",
            policy_gaps=(gap(PolicyType.DETECTION),),
            primary_gap_index=0,
        )
        runner, _, _ = orchestrator(diagnosis, capability=CapabilityKind.CODE)
        execution = runner.execute(request())
        candidate = execution.candidate_defense_version
        self.assertEqual(execution.run.current_state, RunState.VALIDATING)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(candidate["base_version"], "v1")
        self.assertEqual(candidate["candidate_id"], "candidate-build-1")
        self.assertEqual(candidate["created_at"], "2026-09-12T01:00:00+00:00")
        policies = {item["type"]: item["version"] for item in candidate["policies"]}
        self.assertEqual(policies["detection"], "detection-v2")
        self.assertEqual(policies["scoring"], "scoring-v1")
        self.assertIsNone(candidate["evaluation_id"])

    def test_missing_pattern_stops_before_proposal_due_to_shared_build_contract(self) -> None:
        diagnosis = DiagnosisResult(
            DiagnosisOutcome.CHANGE_NEEDED,
            "Performance degraded",
            policy_gaps=(gap(),),
            primary_gap_index=0,
        )
        runner, planner, builder = orchestrator(diagnosis)
        execution = runner.execute(request("performance_degradation", include_pattern=False))
        self.assertEqual(execution.run.current_state, RunState.NEEDS_MORE_EVIDENCE)
        self.assertEqual(planner.proposal_calls, 0)
        self.assertEqual(builder.calls, [])
        self.assertEqual(execution.evolution_result["action"], "no_change")

    def test_invalid_state_transition_is_rejected(self) -> None:
        run = EvolutionRun("run-test", "new_spec_ready")
        with self.assertRaises(InvalidStateTransition):
            EvolutionStateMachine().transition(
                run, RunState.BUILDING, "LLM cannot skip deterministic states"
            )
        self.assertEqual(run.current_state, RunState.RECEIVED)

    def test_external_request_is_not_mutated(self) -> None:
        diagnosis = DiagnosisResult(DiagnosisOutcome.NO_ACTION, "No action")
        runner, _, _ = orchestrator(diagnosis)
        payload = request()
        original = deepcopy(payload)
        runner.execute(payload)
        self.assertEqual(payload, original)


if __name__ == "__main__":
    unittest.main()
