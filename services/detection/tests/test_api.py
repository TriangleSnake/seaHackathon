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

    async def load_context(self, subject: Subject) -> DetectionContext | None:
        if subject.id == "missing":
            return None
        return DetectionContext(subject=subject, account_ids=[subject.id], evidence=[])


class BrokenRepository(FakeRepository):
    async def load_context(self, subject: Subject) -> DetectionContext | None:
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
    assert response.headers["X-Detection-Policy-Version"] == "baseline-v1"


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
