from __future__ import annotations

import unittest

from app.adapters import SharedContractAdapter
from app.capabilities import DetectionPolicyCapabilityAdapter
from app.domain import (
    CapabilityKind,
    ConfigListOperation,
    DETECTION_CHAT_REQUEST_PHRASES_PATH,
    DetectionPolicyChange,
    PolicyChangeProposal,
    PolicyType,
)


def proposal(
    *changes: DetectionPolicyChange,
    target: PolicyType = PolicyType.DETECTION,
    base_policy_version: str | None = "baseline-v1",
) -> PolicyChangeProposal:
    return PolicyChangeProposal(
        proposal_id="proposal-config",
        target_policy=target,
        base_defense_version="DV-001",
        objective="Improve detection coverage",
        requested_behavior="Apply an approved phrase-list change",
        provenance={"source": "test"},
        base_policy_version=base_policy_version,
        detection_policy_changes=changes,
    )


def add_phrase(value: str = "付款") -> DetectionPolicyChange:
    return DetectionPolicyChange(
        path=DETECTION_CHAT_REQUEST_PHRASES_PATH,
        operation=ConfigListOperation.ADD,
        values=(value,),
    )


class DetectionPolicyChangeTests(unittest.TestCase):
    def test_change_requires_safe_path_typed_operation_and_nonblank_unique_values(
        self,
    ) -> None:
        invalid_arguments = (
            {"path": "../rule_based.chat_request_phrases"},
            {"operation": "add"},
            {"values": ["付款"]},
            {"values": ()},
            {"values": (" ",)},
            {"values": ("付款 ",)},
            {"values": ("付款", "付款")},
        )
        defaults = {
            "path": DETECTION_CHAT_REQUEST_PHRASES_PATH,
            "operation": ConfigListOperation.ADD,
            "values": ("付款",),
        }
        for overrides in invalid_arguments:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    DetectionPolicyChange(**(defaults | overrides))


class DetectionPolicyCapabilityAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = DetectionPolicyCapabilityAdapter()

    def test_supported_phrase_change_resolves_to_config(self) -> None:
        change = add_phrase()

        directive = self.adapter.resolve(proposal(change))

        self.assertIs(directive.kind, CapabilityKind.CONFIG)
        self.assertEqual(directive.base_policy_version, "baseline-v1")
        self.assertEqual(directive.detection_policy_changes, (change,))
        self.assertEqual(
            directive.boundary.allowed_paths, ("candidate/detection/",)
        )

    def test_unstructured_detection_behavior_resolves_to_deferred_code_path(
        self,
    ) -> None:
        directive = self.adapter.resolve(proposal())

        self.assertIs(directive.kind, CapabilityKind.CODE)
        self.assertIn("cannot be expressed", directive.reason)

    def test_config_field_outside_allowlist_resolves_to_code(self) -> None:
        unsupported = DetectionPolicyChange(
            path="anomaly.messages_per_hour",
            operation=ConfigListOperation.ADD,
            values=("5",),
        )

        directive = self.adapter.resolve(proposal(unsupported))

        self.assertIs(directive.kind, CapabilityKind.CODE)
        self.assertIn("Only chat request phrase-list", directive.reason)

    def test_missing_baseline_and_wrong_policy_are_unsupported(self) -> None:
        missing = self.adapter.resolve(proposal(add_phrase(), base_policy_version=None))
        wrong_policy = self.adapter.resolve(
            proposal(add_phrase(), target=PolicyType.SCORING)
        )

        self.assertIs(missing.kind, CapabilityKind.UNSUPPORTED)
        self.assertIs(wrong_policy.kind, CapabilityKind.UNSUPPORTED)

    def test_build_request_carries_structured_approved_mutation(self) -> None:
        change = add_phrase()
        candidate_proposal = proposal(change)
        payload = SharedContractAdapter().build_request(
            "build-config", _context(), candidate_proposal
        )

        self.assertEqual(payload["config"]["base_policy_version"], "baseline-v1")
        self.assertEqual(
            payload["config"]["detection_policy_changes"],
            [
                {
                    "path": DETECTION_CHAT_REQUEST_PHRASES_PATH,
                    "operation": "add",
                    "values": ["付款"],
                }
            ],
        )

    def test_candidate_result_factory_uses_only_shared_contract_fields(self) -> None:
        change = {
            "target": "detection",
            "operation": "modify",
            "artifact_path": "candidate/DP-CAND-001.json",
            "summary": "Fixture",
        }
        result = SharedContractAdapter().candidate_result(
            candidate_id="candidate-1",
            build_id="build-1",
            base_defense_version="DV-001",
            status="built",
            changes=(change,),
            artifact_root="candidate/",
            build_log_ref=None,
        )
        change["summary"] = "mutated after mapping"

        self.assertEqual(
            set(result),
            {
                "candidate_id",
                "build_id",
                "base_defense_version",
                "status",
                "changes",
                "artifact_root",
                "build_log_ref",
            },
        )
        self.assertEqual(result["changes"][0]["summary"], "Fixture")


def _context():
    from app.domain import EvolutionContext, TriggerType

    return EvolutionContext(
        trigger_type=TriggerType.NEW_SPEC_READY,
        trigger_context={},
        current_defense_version="DV-001",
        system_performance={},
        pattern_spec={"pattern_id": "pattern-config"},
    )


if __name__ == "__main__":
    unittest.main()
