import unittest

from app.handoff import build_investigation_payload
from app.models import PatrolResult


class HandoffPayloadTests(unittest.TestCase):
    def test_includes_reason_signals_and_evidence(self):
        result = PatrolResult.model_validate({
            "run_id": "run-1", "strategy": "exploit",
            "policy_ref": {"id": "patrol-exploit", "version": "test"},
            "discoveries": [{"subject": {"type": "account", "id": "A"},
                "hypothesis": "coordinated abuse", "reason": "shared device",
                "observed_signals": [{"name": "shared_device", "description": "same device", "evidence_refs": ["E1"]}],
                "counter_signals": [], "priority": 0.8, "evidence_refs": ["E1"]}],
            "evidence": [{"id": "E1", "source": "environment", "type": "login", "data": {"device_id": "D1"}}],
        })
        payload = build_investigation_payload(result, result.discoveries[0])
        self.assertEqual(payload["detection_result"]["triggers"][0]["reason"], "same device")
        self.assertEqual(payload["detection_result"]["evidence"][0]["id"], "E1")
        self.assertEqual(payload["detection_result"]["triggers"][0]["raw_result"]["hypothesis"], "coordinated abuse")


if __name__ == "__main__":
    unittest.main()
