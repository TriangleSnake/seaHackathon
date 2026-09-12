from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.context import DetectionContext
from app.domain.models import Subject
from app.main import create_app
from app.settings import Settings


class FakeRepository:
    async def health(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def load_context(self, subject: Subject, required_evidence: set[str] | None = None) -> DetectionContext | None:
        if subject.id == "missing":
            return None
        return DetectionContext(subject=subject, account_ids=[subject.id], evidence=[])


class BrokenRepository(FakeRepository):
    async def load_context(self, subject: Subject, required_evidence: set[str] | None = None) -> DetectionContext | None:
        raise OSError("database offline")


def make_client() -> TestClient:
    settings = Settings(
        service_name="test-detection",
        database_url="postgresql://unused",
        database_pool_size=1,
        openai_api_key=None,
        openai_model="gpt-5.4-mini",
    )
    return TestClient(create_app(settings=settings, repository=FakeRepository()))


def make_broken_client() -> TestClient:
    settings = Settings(
        service_name="test-detection",
        database_url="postgresql://unused",
        database_pool_size=1,
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
    )
    return TestClient(create_app(settings=settings, repository=BrokenRepository()))


def test_health_and_request_id() -> None:
    with make_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "test-detection"}
    assert response.headers["X-Request-ID"]


def test_ready_checks_database() -> None:
    with make_client() as client:
        response = client.get("/ready", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependencies": {"database": "ok"}}
    assert response.headers["X-Request-ID"] == "request-123"


def test_detect_returns_shared_contract() -> None:
    with make_client() as client:
        response = client.post(
            "/detect",
            json={"subject": {"type": "account", "id": "ACC-0001"}},
        )

    assert response.status_code == 200
    assert response.json()["subject"] == {"type": "account", "id": "ACC-0001"}
    assert response.json()["detected"] is False
    assert response.json()["triggers"] == []
    assert response.json()["evidence"] == []
    assert response.json()["policy_ref"] == {"type": "detection", "version": "baseline-v1"}
    assert [item["component_id"] for item in response.json()["component_results"]] == [
        "marketplace-rules",
        "behavior-anomaly",
    ]
    assert response.headers["X-Detection-Policy-Version"] == "baseline-v1"


def test_policy_can_be_validated_and_tested_without_publishing() -> None:
    policy = {
        "version": "review-v1",
        "default_checks": ["rule_based"],
        "rule_based": {
            "active_report_statuses": ["open"],
            "chat_request_phrases": ["outside"],
            "chat_negations": ["do not"],
            "risk_domain_suffixes": [".invalid"],
            "sensitive_security_events": ["password_changed"],
            "access_window_minutes": 60,
            "reused_image_min_products": 2,
            "delivery_claim_terms": ["delivered"],
        },
        "anomaly": {
            "payment_instruments_per_hour": 3,
            "login_countries_per_day": 3,
            "login_devices_per_day": 3,
            "messages_per_hour": 10,
            "listings_per_hour": 10,
            "disputes_per_week": 3,
        },
        "llm_classifier": {"confidence_threshold": 0.8},
        "components": [
            {
                "id": "rules-next",
                "type": "rule_based",
                "version": "builtin-v1",
                "config": {"access_window_minutes": 30},
            }
        ],
    }

    with make_client() as client:
        validated = client.post("/policies/detection/validate", json=policy)
        tested = client.post(
            "/policies/detection/test",
            json={"policy": policy, "request": {"subject": {"type": "account", "id": "ACC-0001"}}},
        )

    assert validated.status_code == 200
    assert validated.json() == {"valid": True, "version": "review-v1"}
    assert tested.status_code == 200
    assert tested.json()["policy_ref"]["version"] == "review-v1"
    assert tested.json()["component_results"][0]["component_id"] == "rules-next"


def test_detect_rejects_unknown_fields() -> None:
    with make_client() as client:
        response = client.post(
            "/detect",
            json={
                "subject": {"type": "account", "id": "ACC-0001"},
                "unexpected": True,
            },
        )

    assert response.status_code == 422


def test_detect_returns_404_for_unknown_subject() -> None:
    with make_client() as client:
        response = client.post(
            "/detect",
            json={"subject": {"type": "account", "id": "missing"}},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "subject_not_found"


def test_detect_rejects_explicit_null_contract_fields() -> None:
    invalid_payloads = [
        {"subject": {"type": "account", "id": "ACC-0001"}, "requested_checks": None},
        {"subject": {"type": "account", "id": "ACC-0001"}, "trigger_context": None},
        {
            "subject": {"type": "account", "id": "ACC-0001"},
            "trigger_context": {"source": None},
        },
    ]

    with make_client() as client:
        responses = [client.post("/detect", json=payload) for payload in invalid_payloads]

    assert [response.status_code for response in responses] == [422, 422, 422]


def test_detect_returns_503_when_database_fails() -> None:
    with make_broken_client() as client:
        response = client.post(
            "/detect",
            json={"subject": {"type": "account", "id": "ACC-0001"}},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"


def test_detect_fails_explicitly_for_unknown_policy_version() -> None:
    with make_client() as client:
        response = client.post(
            "/detect",
            json={
                "subject": {"type": "account", "id": "ACC-0001"},
                "policy_ref": {"type": "detection", "version": "missing-v9"},
            },
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "policy_not_found"
