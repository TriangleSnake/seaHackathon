from __future__ import annotations

import sys
import unittest
from pathlib import Path


EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_ROOT))

from app.datasets import BuilderDatasetReader, EvaluationDatasetReader
from app.detection import ContractDetectionRunner, DetectionPolicyEvaluator
from app.errors import DatasetAccessError, HoldoutAccessError, UnsupportedPolicyError
from app.gates import StaticDetectionGateProvider, load_trusted_detection_gates
from app.models import DatasetPhase, DatasetRef, EvaluationDataset, EvaluationPlan, PolicyType
from app.router import build_default_router
from app.service import EvaluationService
from fixtures.detection_scenario import (
    FixtureDatasetSource,
    FixturePlanResolver,
    FixtureRuleDetectionRunner,
    detection_cases,
)


VALIDATION_REF = DatasetRef(DatasetPhase.VALIDATION, "fixture://detection/validation-v1")
HOLDOUT_REF = DatasetRef(DatasetPhase.HOLDOUT, "fixture://detection/holdout-v1")


class EvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = FixtureRuleDetectionRunner()
        config_path = EVALUATOR_ROOT / "config" / "hackathon_detection_gates.json"
        self.gate_provider = StaticDetectionGateProvider(
            load_trusted_detection_gates(config_path)
        )
        self.detection = DetectionPolicyEvaluator(
            self.runner,
            self.gate_provider,
        )
        self.router = build_default_router(self.detection)
        datasets = (
            EvaluationDataset(VALIDATION_REF, detection_cases()),
            EvaluationDataset(HOLDOUT_REF, detection_cases()),
        )
        self.source = FixtureDatasetSource(datasets)
        plans = {
            "candidate-a": _plan(PolicyType.DETECTION, "detection/candidate-a"),
            "candidate-b": _plan(PolicyType.DETECTION, "detection/candidate-b"),
            "candidate-scoring": _plan(PolicyType.SCORING, "scoring/candidate-v1"),
        }
        self.service = EvaluationService(
            router=self.router,
            plan_resolver=FixturePlanResolver(plans),
            datasets=EvaluationDatasetReader(self.source),
        )

    def test_router_selects_detection_evaluator(self) -> None:
        self.assertIs(self.router.get(PolicyType.DETECTION), self.detection)

    def test_unsupported_policy_fails_explicitly(self) -> None:
        for policy_type in (
            PolicyType.SCORING,
            PolicyType.EXPLORATION,
            PolicyType.INVESTIGATION,
            PolicyType.ASSOCIATION,
        ):
            self.assertIsNotNone(self.router.get(policy_type))
        with self.assertRaisesRegex(
            UnsupportedPolicyError, "'scoring' is not implemented"
        ):
            self.service.evaluate(_request("candidate-scoring"))

    def test_contract_runner_adapts_existing_detection_shapes(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def execute(policy_ref: str, request: dict[str, object]) -> dict[str, object]:
            calls.append((policy_ref, request))
            return {"detected": True, "triggers": [{"type": "fixture"}]}

        runner = ContractDetectionRunner(execute)
        decision = runner.run("detection/policy-v2", detection_cases()[0].input)
        self.assertTrue(decision.detected)
        self.assertEqual(decision.trigger_count, 1)
        self.assertEqual(calls[0][0], "detection/policy-v2")
        self.assertEqual(
            calls[0][1]["subject"],
            {"type": "account", "id": "acct-fraud-banned"},
        )
        self.assertNotIn("facts", calls[0][1])

    def test_baseline_and_candidate_run_on_same_dataset_inputs(self) -> None:
        self.service.evaluate(_request("candidate-b"))
        baseline_calls = self.runner.calls[:8]
        candidate_calls = self.runner.calls[8:]
        self.assertEqual(
            [case_id for _, case_id, _ in baseline_calls],
            [case_id for _, case_id, _ in candidate_calls],
        )
        self.assertEqual(
            [object_id for _, _, object_id in baseline_calls],
            [object_id for _, _, object_id in candidate_calls],
        )

    def test_detection_metrics_are_calculated_correctly(self) -> None:
        candidate_a = self.service.evaluate(_request("candidate-a"))
        candidate_b = self.service.evaluate(_request("candidate-b"))

        self.assertEqual(candidate_a["baseline_metrics"]["precision"], 1.0)
        self.assertEqual(candidate_a["baseline_metrics"]["recall"], 0.5)
        self.assertEqual(candidate_a["baseline_metrics"]["false_positive_count"], 0)
        self.assertEqual(candidate_a["baseline_metrics"]["trigger_volume"], 2)

        self.assertEqual(candidate_a["candidate_metrics"]["precision"], 0.5)
        self.assertEqual(candidate_a["candidate_metrics"]["recall"], 1.0)
        self.assertEqual(candidate_a["candidate_metrics"]["f1"], 2 / 3)
        self.assertEqual(candidate_a["candidate_metrics"]["false_positive_count"], 4)
        self.assertEqual(candidate_a["candidate_metrics"]["false_positive_rate"], 1.0)
        self.assertEqual(candidate_a["candidate_metrics"]["trigger_volume"], 8)

        self.assertEqual(candidate_b["candidate_metrics"]["precision"], 0.8)
        self.assertEqual(candidate_b["candidate_metrics"]["recall"], 1.0)
        self.assertAlmostEqual(candidate_b["candidate_metrics"]["f1"], 8 / 9)
        self.assertEqual(candidate_b["candidate_metrics"]["false_positive_count"], 1)
        self.assertEqual(candidate_b["candidate_metrics"]["false_positive_rate"], 0.25)
        self.assertEqual(candidate_b["candidate_metrics"]["trigger_volume"], 5)

    def test_incremental_values_are_calculated_against_baseline(self) -> None:
        result = self.service.evaluate(_request("candidate-b"))
        incremental = result["incremental_value"]
        self.assertEqual(incremental["new_fraud_hits"], 2)
        self.assertEqual(incremental["additional_false_positives"], 1)
        self.assertEqual(incremental["fraud_hits_lost"], 0)
        self.assertEqual(incremental["false_positives_removed"], 0)
        self.assertEqual(incremental["trigger_volume_delta"], 3)
        self.assertAlmostEqual(incremental["precision_delta"], -0.2)
        self.assertEqual(incremental["recall_delta"], 0.5)
        self.assertEqual(incremental["false_positive_count_delta"], 1)
        self.assertEqual(incremental["false_positive_rate_delta"], 0.25)

    def test_candidate_a_is_valid_but_fails_effectiveness_gates(self) -> None:
        result = self.service.evaluate(_request("candidate-a"))
        self.assertTrue(result["implementation_valid"])
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            "Candidate adds 4 false positives relative to baseline.",
            result["regressions"],
        )
        self.assertTrue(
            any("temporary maximum is 1" in reason for reason in result["failure_reasons"])
        )

    def test_candidate_b_passes_effectiveness_gates(self) -> None:
        result = self.service.evaluate(_request("candidate-b"))
        self.assertTrue(result["implementation_valid"])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["failure_reasons"], [])

    def test_runtime_failure_is_invalid_implementation_not_effectiveness_failure(self) -> None:
        class FailingCandidateRunner(FixtureRuleDetectionRunner):
            def run(self, policy_ref, case_input):
                if policy_ref == "detection/candidate-b":
                    raise RuntimeError("candidate artifact cannot load")
                return super().run(policy_ref, case_input)

        evaluator = DetectionPolicyEvaluator(
            FailingCandidateRunner(), self.gate_provider
        )
        service = EvaluationService(
            router=build_default_router(evaluator),
            plan_resolver=FixturePlanResolver(
                {"candidate-b": _plan(PolicyType.DETECTION, "detection/candidate-b")}
            ),
            datasets=EvaluationDatasetReader(self.source),
        )
        result = service.evaluate(_request("candidate-b"))
        self.assertFalse(result["implementation_valid"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["baseline_metrics"]["recall"], 0.5)
        self.assertIn("candidate artifact cannot load", result["failure_reasons"][0])

    def test_candidate_request_cannot_override_fixed_gates(self) -> None:
        permissive = _request(
            "candidate-a", thresholds={"maximum_additional_false_positives": 999}
        )
        hostile = _request("candidate-b", thresholds={"minimum_precision": 0.999})
        self.assertEqual(self.service.evaluate(permissive)["status"], "failed")
        self.assertEqual(self.service.evaluate(hostile)["status"], "passed")

    def test_validation_and_holdout_are_distinct_capabilities(self) -> None:
        builder_reader = BuilderDatasetReader(self.source)
        inputs = builder_reader.load_detection_inputs(VALIDATION_REF)
        self.assertEqual(len(inputs), 8)
        self.assertFalse(hasattr(inputs[0], "is_fraud"))

        calls_before_holdout_attempt = tuple(self.source.load_calls)
        with self.assertRaisesRegex(HoldoutAccessError, "evaluator-only"):
            builder_reader.load_detection_inputs(HOLDOUT_REF)
        self.assertEqual(tuple(self.source.load_calls), calls_before_holdout_attempt)

        self.service.evaluate(_request("candidate-b", dataset_ref=HOLDOUT_REF))
        self.assertIs(self.source.load_calls[-1].phase, DatasetPhase.HOLDOUT)

    def test_dataset_phases_cannot_be_aggregated_into_one_result(self) -> None:
        payload = _request("candidate-b")
        payload["datasets"].append({"name": "holdout", "ref": HOLDOUT_REF.ref})
        with self.assertRaisesRegex(DatasetAccessError, "evaluated separately"):
            self.service.evaluate(payload)

    def test_result_has_only_shared_evaluation_result_fields(self) -> None:
        result = self.service.evaluate(_request("candidate-b"))
        self.assertEqual(
            set(result),
            {
                "evaluation_id",
                "candidate_id",
                "status",
                "implementation_valid",
                "candidate_metrics",
                "baseline_metrics",
                "incremental_value",
                "regressions",
                "failure_reasons",
            },
        )
        self.assertEqual(
            set(result["candidate_metrics"]),
            {
                "precision",
                "recall",
                "f1",
                "false_positive_count",
                "false_positive_rate",
                "trigger_volume",
            },
        )


def _plan(policy_type: PolicyType, candidate_policy_ref: str) -> EvaluationPlan:
    return EvaluationPlan(
        policy_type=policy_type,
        baseline_defense_version="defense-v1",
        baseline_policy_ref="detection/baseline-v1",
        candidate_policy_ref=candidate_policy_ref,
    )


def _request(
    candidate_id: str,
    dataset_ref: DatasetRef = VALIDATION_REF,
    thresholds: dict[str, object] | None = None,
) -> dict[str, object]:
    request: dict[str, object] = {
        "evaluation_id": f"eval-{candidate_id}",
        "candidate_id": candidate_id,
        "baseline_defense_version": {"version": "defense-v1"},
        "datasets": [{"name": dataset_ref.phase.value, "ref": dataset_ref.ref}],
    }
    if thresholds is not None:
        request["thresholds"] = thresholds
    return request


if __name__ == "__main__":
    unittest.main()
