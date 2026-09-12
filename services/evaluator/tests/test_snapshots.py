from __future__ import annotations

import sys
import unittest
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_ROOT))

from app.datasets import EvaluationDatasetReader
from app.detection import DetectionPolicyEvaluator
from app.errors import BaselineExecutionError, SnapshotGuardError
from app.gates import StaticDetectionGateProvider, load_trusted_detection_gates
from app.models import (
    DatasetPhase,
    DatasetRef,
    DatasetSnapshot,
    EvaluationDataset,
    EvaluationPlan,
    PolicyType,
)
from app.router import build_default_router
from app.service import EvaluationService
from app.snapshots import EnvironmentSnapshotGuard
from fixtures.detection_scenario import (
    FixtureDatasetSource,
    FixturePlanResolver,
    FixtureRuleDetectionRunner,
    detection_cases,
)


SIMULATION_TIME = datetime.fromisoformat("2026-09-10T12:00:00+08:00")
DATASET_SNAPSHOT = DatasetSnapshot(
    scenario_name="taiwan-marketplace-20260912",
    simulation_time=SIMULATION_TIME,
)
VALIDATION_REF = DatasetRef(
    DatasetPhase.VALIDATION, "manifest://detection/validation-v1"
)


class SequenceOverviewSource:
    def __init__(
        self,
        *overviews: Mapping[str, Any],
        on_read: Callable[[], None] | None = None,
    ) -> None:
        self._overviews = list(overviews)
        self._on_read = on_read
        self.calls = 0

    def get_environment_overview(self) -> Mapping[str, Any]:
        if self._on_read is not None:
            self._on_read()
        try:
            overview = self._overviews[self.calls]
        except IndexError as exc:
            raise AssertionError("Environment overview read too many times") from exc
        self.calls += 1
        return overview


class SnapshotGuardTests(unittest.TestCase):
    def test_matching_snapshot_brackets_both_policy_runs(self) -> None:
        runner = FixtureRuleDetectionRunner()
        policy_call_counts: list[int] = []
        source = SequenceOverviewSource(
            _overview(
                simulation_time="2026-09-10 04:00:00+00:00",
                updated_at="2026-09-10 04:00:00+00:00",
            ),
            _overview(
                simulation_time="2026-09-10T12:00:00+08:00",
                updated_at="2026-09-10T12:00:00+08:00",
            ),
            on_read=lambda: policy_call_counts.append(len(runner.calls)),
        )
        service = _service(runner, _snapshot_dataset(), source)

        result = service.evaluate(_request())

        self.assertEqual(result["status"], "passed")
        self.assertEqual(source.calls, 2)
        self.assertEqual(policy_call_counts, [0, 16])
        self.assertEqual(
            [policy_ref for policy_ref, _, _ in runner.calls[:8]],
            ["detection/baseline-v1"] * 8,
        )
        self.assertEqual(
            [policy_ref for policy_ref, _, _ in runner.calls[8:]],
            ["detection/candidate-b"] * 8,
        )

    def test_pre_evaluation_mismatch_prevents_policy_execution(self) -> None:
        runner = FixtureRuleDetectionRunner()
        source = SequenceOverviewSource(
            _overview(scenario_name="different-scenario"),
        )
        service = _service(runner, _snapshot_dataset(), source)

        with self.assertRaisesRegex(SnapshotGuardError, "does not match"):
            service.evaluate(_request())

        self.assertEqual(runner.calls, [])
        self.assertEqual(source.calls, 1)

    def test_post_evaluation_clock_change_fails_closed(self) -> None:
        runner = FixtureRuleDetectionRunner()
        source = SequenceOverviewSource(
            _overview(),
            _overview(
                simulation_time="2026-09-10T12:01:00+08:00",
                updated_at="2026-09-10T12:01:00+08:00",
            ),
        )
        service = _service(runner, _snapshot_dataset(), source)

        with self.assertRaisesRegex(SnapshotGuardError, "changed during evaluation"):
            service.evaluate(_request())

        self.assertEqual(len(runner.calls), 16)
        self.assertEqual(source.calls, 2)

    def test_post_evaluation_updated_at_change_fails_closed(self) -> None:
        runner = FixtureRuleDetectionRunner()
        source = SequenceOverviewSource(
            _overview(),
            _overview(updated_at="2026-09-10T12:00:01+08:00"),
        )
        service = _service(runner, _snapshot_dataset(), source)

        with self.assertRaisesRegex(SnapshotGuardError, "changed during evaluation"):
            service.evaluate(_request())

        self.assertEqual(len(runner.calls), 16)
        self.assertEqual(source.calls, 2)

    def test_post_check_runs_when_evaluator_raises(self) -> None:
        class FailingBaselineRunner(FixtureRuleDetectionRunner):
            def run(self, policy_ref, case_input):
                if policy_ref == "detection/baseline-v1":
                    raise RuntimeError("baseline unavailable")
                return super().run(policy_ref, case_input)

        runner = FailingBaselineRunner()
        source = SequenceOverviewSource(_overview(), _overview())
        service = _service(runner, _snapshot_dataset(), source)

        with self.assertRaises(BaselineExecutionError):
            service.evaluate(_request())

        self.assertEqual(source.calls, 2)

    def test_malformed_or_naive_overview_fails_closed(self) -> None:
        malformed = (
            {},
            {"simulation": None},
            _overview(simulation_time="not-a-time"),
            _overview(simulation_time="2026-09-10T12:00:00"),
            _overview(updated_at="2026-09-10T12:00:00"),
        )
        for overview in malformed:
            with self.subTest(overview=overview):
                runner = FixtureRuleDetectionRunner()
                source = SequenceOverviewSource(overview)
                service = _service(runner, _snapshot_dataset(), source)
                with self.assertRaises(SnapshotGuardError):
                    service.evaluate(_request())
                self.assertEqual(runner.calls, [])

    def test_snapshot_backed_dataset_requires_configured_guard(self) -> None:
        runner = FixtureRuleDetectionRunner()
        service = _service(runner, _snapshot_dataset(), source=None)

        with self.assertRaisesRegex(SnapshotGuardError, "requires"):
            service.evaluate(_request())

        self.assertEqual(runner.calls, [])

    def test_configured_guard_rejects_dataset_without_snapshot(self) -> None:
        runner = FixtureRuleDetectionRunner()
        dataset = EvaluationDataset(VALIDATION_REF, detection_cases())
        source = SequenceOverviewSource(_overview())
        service = _service(runner, dataset, source)

        with self.assertRaisesRegex(SnapshotGuardError, "Every dataset"):
            service.evaluate(_request())

        self.assertEqual(runner.calls, [])
        self.assertEqual(source.calls, 0)

    def test_mixed_dataset_snapshots_are_rejected_before_environment_read(self) -> None:
        second_ref = DatasetRef(
            DatasetPhase.VALIDATION, "manifest://detection/validation-v2"
        )
        different = DatasetSnapshot(
            scenario_name=DATASET_SNAPSHOT.scenario_name,
            simulation_time=datetime.fromisoformat("2026-09-11T12:00:00+08:00"),
        )
        datasets = (
            _snapshot_dataset(),
            EvaluationDataset(second_ref, (), snapshot=different),
        )
        runner = FixtureRuleDetectionRunner()
        source = SequenceOverviewSource(_overview())
        service = _service(runner, datasets, source)
        request = _request()
        request["datasets"].append(
            {"name": "validation", "ref": second_ref.ref}
        )

        with self.assertRaisesRegex(SnapshotGuardError, "same Environment snapshot"):
            service.evaluate(request)

        self.assertEqual(runner.calls, [])
        self.assertEqual(source.calls, 0)


def _overview(
    *,
    scenario_name: str = "taiwan-marketplace-20260912",
    simulation_time: str = "2026-09-10T12:00:00+08:00",
    updated_at: str | None = "2026-09-10T12:00:00+08:00",
) -> dict[str, object]:
    return {
        "simulation": {
            "scenario_name": scenario_name,
            "simulation_time": simulation_time,
            "initial_time": "2026-09-01T00:00:00+08:00",
            "updated_at": updated_at,
        },
        "counts": {"messages": 440},
    }


def _snapshot_dataset() -> EvaluationDataset:
    return EvaluationDataset(
        VALIDATION_REF,
        detection_cases(),
        snapshot=DATASET_SNAPSHOT,
    )


def _service(
    runner: FixtureRuleDetectionRunner,
    datasets: EvaluationDataset | tuple[EvaluationDataset, ...],
    source: SequenceOverviewSource | None,
) -> EvaluationService:
    available = datasets if isinstance(datasets, tuple) else (datasets,)
    dataset_source = FixtureDatasetSource(available)
    plan = EvaluationPlan(
        policy_type=PolicyType.DETECTION,
        baseline_defense_version="defense-v1",
        baseline_policy_ref="detection/baseline-v1",
        candidate_policy_ref="detection/candidate-b",
    )
    gates = StaticDetectionGateProvider(
        load_trusted_detection_gates(
            EVALUATOR_ROOT / "config" / "hackathon_detection_gates.json"
        )
    )
    evaluator = DetectionPolicyEvaluator(runner, gates)
    guard = EnvironmentSnapshotGuard(source) if source is not None else None
    return EvaluationService(
        router=build_default_router(evaluator),
        plan_resolver=FixturePlanResolver({"candidate-b": plan}),
        datasets=EvaluationDatasetReader(dataset_source),
        snapshot_guard=guard,
    )


def _request() -> dict[str, object]:
    return {
        "evaluation_id": "eval-snapshot",
        "candidate_id": "candidate-b",
        "baseline_defense_version": {"version": "defense-v1"},
        "datasets": [{"name": "validation", "ref": VALIDATION_REF.ref}],
    }


if __name__ == "__main__":
    unittest.main()
