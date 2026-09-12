from __future__ import annotations

import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.adapters import SharedContractAdapter
from app.domain import (
    DiagnosisOutcome,
    EvolutionRun,
    PolicyChangeProposal,
    PolicyMutationIntent,
    PolicyType,
)
from app.planner import (
    OpenAIEvolutionPlanner,
    PlannerBackendError,
    PlannerConfigurationError,
    PlannerResponseError,
)


def request() -> dict:
    return {
        "trigger": {
            "type": "new_spec_ready",
            "context": {
                "source": "test",
                "holdout_labels": ["HOLDOUT_SECRET"],
                "secret_holdout_dataset": ["HOLDOUT_DATASET_SECRET"],
            },
        },
        "current_defense_version": {"version": "DV-001"},
        "system_performance": {
            "precision": 0.7,
            "ground_truth": "GROUND_TRUTH_SECRET",
        },
        "pattern_spec": {
            "pattern_id": "pattern-1",
            "name": "New request language",
            "observed_signals": [
                {
                    "field": "message.text",
                    "operator": "contains",
                    "value": "unseen wording",
                }
            ],
            "current_defense_gap": "Current phrase configuration misses wording",
            "confidence": 0.9,
            "evidence_refs": ["evidence-1"],
        },
    }


def diagnosis_output() -> dict:
    return {
        "outcome": "CHANGE_NEEDED",
        "reason": "A detection phrase-list gap is supported by the pattern.",
        "policy_gaps": [
            {
                "policy_type": "detection",
                "severity": "high",
                "confidence": 0.9,
                "symptom": "The request wording is missed.",
                "hypothesized_cause": "The phrase list lacks equivalent language.",
                "evidence_refs": ["evidence-1"],
                "reasoning": "The observed signal maps to a configurable phrase list.",
            }
        ],
        "considered_policies": ["detection"],
        "primary_gap_index": 0,
    }


def proposal_output(
    *,
    phrase: str = "new request wording",
    path: str = "rule_based.chat_request_phrases",
    requested_behavior: str = "Recognize equivalent suspicious chat requests.",
) -> dict:
    return {
        "objective": "Cover the newly observed request language.",
        "requested_behavior": requested_behavior,
        "required_signals": ["message.text"],
        "expected_impact": "Increase coverage while retaining existing behavior.",
        "known_risks": ["Broader phrases can increase false positives."],
        "mutation_intent": {
            "operation": "append_unique",
            "path": path,
            "values": [phrase],
            "rationale": "The pattern identifies semantically equivalent wording.",
        },
    }


class FakeResponses:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        raw = output if isinstance(output, str) else json.dumps(output)
        return SimpleNamespace(
            id=f"response-{len(self.calls)}",
            status="completed",
            output_text=raw,
            output=[],
        )


class FakeClient:
    def __init__(self, outputs: list[object]) -> None:
        self.responses = FakeResponses(outputs)


class OpenAIEvolutionPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = SharedContractAdapter().evolution_context(request())

    def test_structured_diagnosis_and_config_proposal_validate_to_domain_models(
        self,
    ) -> None:
        client = FakeClient([diagnosis_output(), proposal_output()])
        planner = OpenAIEvolutionPlanner(client, "test-model")
        run = EvolutionRun("run-1", "new_spec_ready")

        diagnosis = planner.diagnose(self.context)
        proposal = planner.propose(run, self.context, diagnosis)

        self.assertEqual(diagnosis.outcome, DiagnosisOutcome.CHANGE_NEEDED)
        self.assertEqual(diagnosis.primary_gap.policy_type, PolicyType.DETECTION)
        self.assertEqual(proposal.proposal_id, "proposal-run-1-iteration-1")
        self.assertEqual(proposal.base_defense_version, "DV-001")
        self.assertEqual(proposal.target_policy, PolicyType.DETECTION)
        self.assertIsInstance(proposal.mutation_intent, PolicyMutationIntent)
        assert proposal.mutation_intent is not None
        self.assertEqual(
            proposal.mutation_intent.path,
            "rule_based.chat_request_phrases",
        )
        self.assertEqual(proposal.provenance["response_id"], "response-2")

        build_request = SharedContractAdapter().build_request(
            "build-1", self.context, proposal
        )
        self.assertEqual(
            build_request["config"]["mutation_intent"],
            {
                "operation": "append_unique",
                "path": "rule_based.chat_request_phrases",
                "values": ["new request wording"],
                "rationale": (
                    "The pattern identifies semantically equivalent wording."
                ),
            },
        )

        for call in client.responses.calls:
            self.assertEqual(call["text"]["format"]["type"], "json_schema")
            self.assertTrue(call["text"]["format"]["strict"])
            self.assertFalse(call["store"])
        proposal_schema = client.responses.calls[1]["text"]["format"]["schema"]
        self.assertNotIn("proposal_id", proposal_schema["properties"])
        self.assertNotIn("base_defense_version", proposal_schema["properties"])

    def test_planner_input_filters_evaluator_owned_material(self) -> None:
        client = FakeClient([diagnosis_output()])
        planner = OpenAIEvolutionPlanner(client, "test-model")

        planner.diagnose(self.context)

        sent = client.responses.calls[0]["input"]
        self.assertIn('"source": "test"', sent)
        self.assertNotIn("HOLDOUT_SECRET", sent)
        self.assertNotIn("HOLDOUT_DATASET_SECRET", sent)
        self.assertNotIn("GROUND_TRUTH_SECRET", sent)
        self.assertNotIn("holdout_labels", sent)
        self.assertNotIn("ground_truth", sent)

    def test_capability_provider_receives_current_context(self) -> None:
        seen_versions: list[str] = []

        def capabilities(context):
            seen_versions.append(context.current_defense_version)
            return {
                "detection": {
                    "kind": "CONFIG",
                    "configurable_fields": [
                        {
                            "path": "rule_based.chat_request_phrases",
                            "value_type": "string_list",
                            "operations": ["append_unique"],
                            "current_values": ["existing wording"],
                        }
                    ],
                }
            }

        client = FakeClient([diagnosis_output(), proposal_output()])
        planner = OpenAIEvolutionPlanner(
            client, "test-model", capability_provider=capabilities
        )

        diagnosis = planner.diagnose(self.context)
        planner.propose(EvolutionRun("run-1", "fixture"), self.context, diagnosis)

        self.assertEqual(seen_versions, ["DV-001", "DV-001"])
        self.assertIn("existing wording", client.responses.calls[1]["input"])

    def test_revision_contains_only_aggregate_feedback_and_prior_proposals(
        self,
    ) -> None:
        previous = PolicyChangeProposal(
            proposal_id="proposal-v1",
            target_policy=PolicyType.DETECTION,
            base_defense_version="DV-001",
            objective="Cover a phrase",
            requested_behavior="Recognize a phrase",
            provenance={"holdout_labels": "HOLDOUT_SECRET"},
            mutation_intent=PolicyMutationIntent(
                operation="append_unique",
                path="rule_based.chat_request_phrases",
                values=("first wording",),
                rationale="Pattern evidence",
            ),
        )
        run = EvolutionRun("run-revision", "new_spec_ready", retry_budget=1)
        run.record_proposal(previous)
        run.record_candidate("candidate-v1", "DV-CAND-v1")
        run.record_evaluation("candidate-v1", "eval-v1", "failed")
        run.iteration = 2
        evaluation = {
            "evaluation_id": "eval-v1",
            "candidate_id": "candidate-v1",
            "status": "failed",
            "failure_reasons": ["Recall did not improve"],
            "regressions": ["Precision decreased"],
            "baseline_metrics": {"precision": 0.8, "recall": 0.4},
            "candidate_metrics": {"precision": 0.7, "recall": 0.4},
            "incremental_value": {"precision": -0.1, "recall": 0.0},
            "holdout_labels": ["HOLDOUT_SECRET"],
            "thresholds": {"editable": "GATE_SECRET"},
        }
        feedback = SharedContractAdapter().revision_feedback(
            evaluation, previous, iteration=1
        )
        diagnosis = _diagnosis()
        client = FakeClient([proposal_output(phrase="revised wording")])
        planner = OpenAIEvolutionPlanner(client, "test-model")

        revised = planner.propose(
            run, self.context, diagnosis, feedback=feedback
        )

        sent = client.responses.calls[0]["input"]
        self.assertIn("Recall did not improve", sent)
        self.assertIn('"precision": -0.1', sent)
        self.assertIn("proposal-v1", sent)
        self.assertIn('"candidate_id": "candidate-v1"', sent)
        self.assertIn('"evaluation_status": "failed"', sent)
        self.assertNotIn("HOLDOUT_SECRET", sent)
        self.assertNotIn("GATE_SECRET", sent)
        self.assertEqual(revised.provenance["revision_of"], "proposal-v1")
        self.assertEqual(revised.proposal_id, "proposal-run-revision-iteration-2")

    def test_malformed_model_json_is_a_controlled_error(self) -> None:
        planner = OpenAIEvolutionPlanner(FakeClient(["not-json"]), "test-model")

        with self.assertRaisesRegex(PlannerResponseError, "malformed JSON"):
            planner.diagnose(self.context)

    def test_backend_failure_is_a_controlled_error(self) -> None:
        planner = OpenAIEvolutionPlanner(
            FakeClient([RuntimeError("service unavailable")]), "test-model"
        )

        with self.assertRaisesRegex(PlannerBackendError, "service unavailable"):
            planner.diagnose(self.context)

    def test_config_mutation_outside_capability_is_rejected(self) -> None:
        client = FakeClient([proposal_output(path="evaluator.pass_threshold")])
        planner = OpenAIEvolutionPlanner(client, "test-model")

        with self.assertRaisesRegex(PlannerResponseError, "outside the current"):
            planner.propose(EvolutionRun("run-1", "fixture"), self.context, _diagnosis())

    def test_protected_mechanism_request_is_rejected(self) -> None:
        client = FakeClient(
            [proposal_output(requested_behavior="Modify evaluator gates to pass.")]
        )
        planner = OpenAIEvolutionPlanner(client, "test-model")

        with self.assertRaisesRegex(PlannerResponseError, "protected mechanism"):
            planner.propose(EvolutionRun("run-1", "fixture"), self.context, _diagnosis())

    def test_artifact_path_in_behavior_is_rejected(self) -> None:
        client = FakeClient(
            [proposal_output(requested_behavior="Write /tmp/policy.json directly.")]
        )
        planner = OpenAIEvolutionPlanner(client, "test-model")

        with self.assertRaisesRegex(PlannerResponseError, "file path"):
            planner.propose(EvolutionRun("run-1", "fixture"), self.context, _diagnosis())

    def test_artifact_path_in_mutation_values_is_rejected(self) -> None:
        client = FakeClient([proposal_output(phrase="/tmp/policy.json")])
        planner = OpenAIEvolutionPlanner(client, "test-model")

        with self.assertRaisesRegex(PlannerResponseError, "file path"):
            planner.propose(EvolutionRun("run-1", "fixture"), self.context, _diagnosis())

    def test_missing_api_key_fails_before_importing_or_calling_openai(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PlannerConfigurationError, "OPENAI_API_KEY"):
                OpenAIEvolutionPlanner.from_env()


def _diagnosis():
    planner = OpenAIEvolutionPlanner(FakeClient([diagnosis_output()]), "test-model")
    return planner.diagnose(
        SharedContractAdapter().evolution_context(request())
    )


if __name__ == "__main__":
    unittest.main()
