from __future__ import annotations

from typing import Optional

from fastapi.testclient import TestClient

from app.api.readiness import ReadinessError
from app.main import create_app
from app.settings import Settings


class ReadyProbe:
    async def check(self, request_id: str) -> None:
        assert request_id

    async def close(self) -> None:
        return None


class UnreadyProbe(ReadyProbe):
    async def check(self, request_id: str) -> None:
        raise ReadinessError("offline")


def make_client(probe: Optional[ReadyProbe] = None) -> TestClient:
    settings = Settings(
        service_name="test-investigation",
        agentgateway_url="http://gateway.test/mcp",
        gateway_timeout_seconds=1,
    )
    app = create_app(settings, readiness_probe=probe)
    return TestClient(app)


def valid_request() -> dict:
    return {
        "case_id": "case-001",
        "detection_result": {
            "detection_id": "detection-001",
            "subject": {"type": "account", "id": "acct-suspicious-1"},
            "policy_ref": {"type": "detection", "version": "baseline-v1"},
            "detected": True,
            "triggers": [
                {
                    "type": "shared_device",
                    "detector": "rule_based",
                    "reason": "Shared device with a banned account",
                    "evidence_refs": ["login-002"],
                }
            ],
            "evidence": [
                {
                    "id": "login-002",
                    "source": "detection",
                    "type": "login_event",
                    "data": {"device_id": "device-shared-001"},
                }
            ],
            "component_results": [
                {
                    "component_id": "marketplace-rules",
                    "detector": "rule_based",
                    "version": "builtin-v1",
                    "status": "completed",
                    "trigger_count": 1,
                    "latency_ms": 0.2,
                }
            ],
        },
        "scoreboard_config_ref": {"version": "development-v1"},
    }


def test_health_and_generated_request_id() -> None:
    with make_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "test-investigation"}
    assert response.headers["X-Request-ID"]


def test_ready_checks_dependencies_and_preserves_request_id() -> None:
    with make_client(ReadyProbe()) as client:
        response = client.get("/ready", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 200
    assert response.json()["dependencies"] == {
        "agentgateway": "ok",
        "database": "ok",
    }
    assert response.headers["X-Request-ID"] == "request-123"


def test_ready_returns_503_when_dependency_is_down() -> None:
    with make_client(UnreadyProbe()) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"


def test_investigate_returns_schema_compatible_placeholder() -> None:
    with make_client() as client:
        response = client.post("/investigate", json=valid_request())

    assert response.status_code == 200
    assert response.headers["X-Investigation-Placeholder"] == "true"
    assert response.json() == {
        "case_id": "case-001",
        "subject": {"type": "account", "id": "acct-suspicious-1"},
        "verdict": "unknown",
        "confidence": 0.0,
        "summary": (
            "Placeholder response: the Investigation API contract is available, "
            "but no agents or scoring rules have run."
        ),
        "findings": [],
        "evidence": [
            {
                "id": "login-002",
                "source": "detection",
                "type": "login_event",
                "ref_id": None,
                "observed_at": None,
                "data": {"device_id": "device-shared-001"},
            }
        ],
        "agents_invoked": [],
        "scoreboard": {
            "placeholder": True,
            "status": "not_started",
            "config_ref": {"version": "development-v1"},
        },
        "stop_reason": "insufficient_evidence",
    }


def test_investigate_rejects_unknown_request_fields() -> None:
    payload = valid_request()
    payload["unexpected"] = True
    with make_client() as client:
        response = client.post("/investigate", json=payload)

    assert response.status_code == 422


def test_investigate_rejects_empty_scoreboard_reference() -> None:
    payload = valid_request()
    payload["scoreboard_config_ref"] = {}
    with make_client() as client:
        response = client.post("/investigate", json=payload)

    assert response.status_code == 422
