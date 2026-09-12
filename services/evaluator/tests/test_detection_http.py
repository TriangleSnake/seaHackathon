from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_ROOT))

from app.detection import (
    DetectionHttpResponse,
    HttpDetectionRunner,
    UrllibDetectionHttpTransport,
)
from app.errors import (
    DetectionHttpError,
    DetectionPolicyNotFoundError,
    DetectionPolicyTraceError,
    DetectionRequestRejectedError,
    DetectionResponseError,
    DetectionTimeoutError,
    DetectionTransportError,
)
from app.models import DetectionInput
from app.settings import DetectionHttpSettings


class MockDetectionTransport:
    def __init__(self, *outcomes: DetectionHttpResponse | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def post(
        self, url: str, payload: dict[str, Any], timeout_seconds: float
    ) -> DetectionHttpResponse:
        self.calls.append(
            (url, json.loads(json.dumps(payload)), timeout_seconds)
        )
        if not self._outcomes:
            raise AssertionError("Mock Detection transport has no response")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class HttpDetectionRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case_input = DetectionInput(
            case_id="case-private-1",
            subject_type="account",
            subject_id="ACC-0001",
            facts={"activity_score": 0.99},
        )

    def test_baseline_request_contains_exact_policy_ref_and_context(self) -> None:
        transport = MockDetectionTransport(_clean_response("baseline-v1"))
        runner = _runner(transport)

        runner.run("baseline-v1", self.case_input)

        self.assertEqual(
            transport.calls,
            [
                (
                    "https://detection.example.test/root/detect",
                    {
                        "subject": {"type": "account", "id": "ACC-0001"},
                        "requested_checks": ["rule_based", "anomaly"],
                        "policy_ref": {
                            "type": "detection",
                            "version": "baseline-v1",
                        },
                        "trigger_context": {
                            "source": "evaluation",
                            "reason": "baseline_candidate_comparison",
                        },
                    },
                    2.5,
                )
            ],
        )

    def test_candidate_request_contains_exact_policy_ref(self) -> None:
        transport = MockDetectionTransport(_clean_response("candidate-v7"))
        runner = _runner(transport)

        runner.run("candidate-v7", self.case_input)

        payload = transport.calls[0][1]
        self.assertEqual(
            payload["policy_ref"],
            {"type": "detection", "version": "candidate-v7"},
        )
        self.assertEqual(payload["requested_checks"], ["rule_based", "anomaly"])

    def test_detected_true_converts_all_triggers_to_volume(self) -> None:
        triggers = [
            {
                "type": "suspicious_chat",
                "detector": "rule_based",
                "rule_id": "RULE-1",
                "reason": "matched rule",
                "raw_result": {"policy_version": "candidate-v7"},
                "evidence_refs": ["EV-1"],
            },
            {
                "type": "activity_spike",
                "detector": "anomaly",
                "reason": "threshold crossed",
                "evidence_refs": ["EV-1"],
            },
        ]
        evidence = [
            {
                "id": "EV-1",
                "source": "environment",
                "type": "login_event",
                "ref_id": None,
                "observed_at": "2026-09-12T00:00:00Z",
                "data": {"country_code": "TW"},
            }
        ]
        transport = MockDetectionTransport(
            _response("candidate-v7", detected=True, triggers=triggers, evidence=evidence)
        )

        decision = _runner(transport).run("candidate-v7", self.case_input)

        self.assertTrue(decision.detected)
        self.assertEqual(decision.trigger_count, 2)

    def test_detected_false_converts_to_zero_triggers_with_traced_policy(self) -> None:
        transport = MockDetectionTransport(
            _response(
                "baseline-v1",
                detected=False,
                headers={"x-detection-policy-version": "baseline-v1"},
            )
        )

        decision = _runner(transport).run("baseline-v1", self.case_input)

        self.assertFalse(decision.detected)
        self.assertEqual(decision.trigger_count, 0)

    def test_policy_not_found_404_is_an_execution_failure(self) -> None:
        transport = MockDetectionTransport(
            DetectionHttpResponse(
                status_code=404,
                headers={},
                body=_json_bytes(
                    {
                        "error": {
                            "code": "policy_not_found",
                            "message": "Detection policy 'missing-v9' was not found.",
                            "request_id": "req-1",
                        }
                    }
                ),
            )
        )

        with self.assertRaises(DetectionPolicyNotFoundError) as raised:
            _runner(transport).run("missing-v9", self.case_input)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.error_code, "policy_not_found")

    def test_missing_policy_header_fails_closed(self) -> None:
        response = _clean_response("baseline-v1")
        response = DetectionHttpResponse(response.status_code, {}, response.body)

        with self.assertRaisesRegex(
            DetectionPolicyTraceError, "missing X-Detection-Policy-Version"
        ):
            _runner(MockDetectionTransport(response)).run(
                "baseline-v1", self.case_input
            )

    def test_policy_header_mismatch_fails_closed(self) -> None:
        response = _response(
            "baseline-v1",
            detected=False,
            headers={"X-Detection-Policy-Version": "fallback-v1"},
        )

        with self.assertRaisesRegex(
            DetectionPolicyTraceError,
            "requested 'baseline-v1'.*reported 'fallback-v1'",
        ):
            _runner(MockDetectionTransport(response)).run(
                "baseline-v1", self.case_input
            )

    def test_malformed_detection_result_is_an_execution_failure(self) -> None:
        malformed_bodies = (
            b"not-json",
            _json_bytes({"detected": False, "triggers": []}),
            _json_bytes(
                {
                    **_result_payload(),
                    "detected": "false",
                }
            ),
            _json_bytes(
                {
                    **_result_payload(),
                    "unexpected": "field",
                }
            ),
        )
        for body in malformed_bodies:
            with self.subTest(body=body):
                response = DetectionHttpResponse(
                    status_code=200,
                    headers={"X-Detection-Policy-Version": "baseline-v1"},
                    body=body,
                )
                with self.assertRaises(DetectionResponseError):
                    _runner(MockDetectionTransport(response)).run(
                        "baseline-v1", self.case_input
                    )

    def test_subject_mismatch_is_an_execution_failure(self) -> None:
        response = _clean_response(
            "baseline-v1", subject={"type": "account", "id": "ACC-other"}
        )

        with self.assertRaisesRegex(DetectionResponseError, "subject does not match"):
            _runner(MockDetectionTransport(response)).run(
                "baseline-v1", self.case_input
            )

    def test_network_error_is_not_converted_to_clean_decision(self) -> None:
        transport = MockDetectionTransport(ConnectionError("connection refused"))

        with self.assertRaisesRegex(DetectionTransportError, "connection refused"):
            _runner(transport).run("baseline-v1", self.case_input)

    def test_timeout_is_not_converted_to_clean_decision(self) -> None:
        transport = MockDetectionTransport(TimeoutError("deadline exceeded"))

        with self.assertRaisesRegex(DetectionTimeoutError, "timed out"):
            _runner(transport).run("baseline-v1", self.case_input)

    def test_api_rejected_subject_or_check_is_an_execution_failure(self) -> None:
        transport = MockDetectionTransport(
            DetectionHttpResponse(
                status_code=422,
                headers={},
                body=_json_bytes(
                    {
                        "detail": [
                            {
                                "loc": ["body", "requested_checks", 0],
                                "msg": "Input should be a supported detector",
                                "type": "literal_error",
                            }
                        ]
                    }
                ),
            )
        )

        with self.assertRaises(DetectionRequestRejectedError) as raised:
            _runner(transport).run("baseline-v1", self.case_input)

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("supported detector", str(raised.exception))

    def test_dependency_503_is_an_execution_failure(self) -> None:
        transport = MockDetectionTransport(
            DetectionHttpResponse(
                status_code=503,
                headers={},
                body=_json_bytes(
                    {
                        "error": {
                            "code": "dependency_unavailable",
                            "message": "A Detection dependency is unavailable.",
                            "request_id": "req-2",
                        }
                    }
                ),
            )
        )

        with self.assertRaises(DetectionHttpError) as raised:
            _runner(transport).run("baseline-v1", self.case_input)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.error_code, "dependency_unavailable")

    def test_private_labels_facts_metadata_and_gates_are_never_transmitted(self) -> None:
        private_input = DetectionInput(
            case_id="validation-case-secret",
            subject_type="message",
            subject_id="MSG-0901",
            facts={
                "is_fraud": True,
                "evaluator_label": "fraud",
                "expected_outcome": "detected",
                "holdout": True,
                "failure_gates": {"minimum_precision": 1.0},
            },
        )
        transport = MockDetectionTransport(
            _clean_response(
                "candidate-v7", subject={"type": "message", "id": "MSG-0901"}
            )
        )

        _runner(transport).run("candidate-v7", private_input)

        payload = transport.calls[0][1]
        self.assertEqual(
            set(payload),
            {"subject", "requested_checks", "policy_ref", "trigger_context"},
        )
        serialized = json.dumps(payload)
        for private_key in (
            "case_id",
            "facts",
            "is_fraud",
            "evaluator_label",
            "expected_outcome",
            "validation",
            "holdout",
            "failure_gates",
        ):
            self.assertNotIn(private_key, serialized)

    def test_settings_load_detection_url_and_timeout_from_environment(self) -> None:
        settings = DetectionHttpSettings.from_env(
            {
                "DETECTION_URL": "http://detection.internal:8123",
                "DETECTION_TIMEOUT_SECONDS": "1.25",
            }
        )

        self.assertEqual(settings.base_url, "http://detection.internal:8123")
        self.assertEqual(settings.timeout_seconds, 1.25)

    def test_settings_require_an_explicit_detection_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "DETECTION_URL must be configured"):
            DetectionHttpSettings.from_env({})

    def test_default_transport_posts_json_with_configured_timeout(self) -> None:
        payload = {
            "subject": {"type": "account", "id": "ACC-0001"},
            "requested_checks": ["rule_based"],
            "policy_ref": {"type": "detection", "version": "baseline-v1"},
            "trigger_context": {
                "source": "evaluation",
                "reason": "baseline_candidate_comparison",
            },
        }
        url_response = _MockUrlResponse(
            _json_bytes(_result_payload()),
            headers={"X-Detection-Policy-Version": "baseline-v1"},
        )

        with patch("app.detection.urlopen", return_value=url_response) as mocked_open:
            response = UrllibDetectionHttpTransport().post(
                "https://detection.example.test/detect", payload, 3.75
            )

        request = mocked_open.call_args.args[0]
        self.assertEqual(request.full_url, "https://detection.example.test/detect")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), payload)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(mocked_open.call_args.kwargs["timeout"], 3.75)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["X-Detection-Policy-Version"], "baseline-v1"
        )


def _runner(transport: MockDetectionTransport) -> HttpDetectionRunner:
    return HttpDetectionRunner(
        ["rule_based", "anomaly"],
        settings=DetectionHttpSettings(
            base_url="https://detection.example.test/root/", timeout_seconds=2.5
        ),
        transport=transport,
    )


def _clean_response(
    policy_version: str,
    *,
    subject: dict[str, str] | None = None,
) -> DetectionHttpResponse:
    return _response(
        policy_version,
        detected=False,
        subject=subject,
    )


def _response(
    policy_version: str,
    *,
    detected: bool,
    subject: dict[str, str] | None = None,
    triggers: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> DetectionHttpResponse:
    return DetectionHttpResponse(
        status_code=200,
        headers=(
            {"X-Detection-Policy-Version": policy_version}
            if headers is None
            else headers
        ),
        body=_json_bytes(
            _result_payload(
                subject=subject,
                detected=detected,
                triggers=triggers,
                evidence=evidence,
            )
        ),
    )


def _result_payload(
    *,
    subject: dict[str, str] | None = None,
    detected: bool = False,
    triggers: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "detection_id": "DET-test-1",
        "subject": subject or {"type": "account", "id": "ACC-0001"},
        "detected": detected,
        "triggers": [] if triggers is None else triggers,
        "evidence": [] if evidence is None else evidence,
    }


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload).encode("utf-8")


class _MockUrlResponse:
    status = 200

    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = body
        self.headers = headers

    def __enter__(self) -> "_MockUrlResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


if __name__ == "__main__":
    unittest.main()
