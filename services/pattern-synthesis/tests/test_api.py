from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.synthesizer import UnavailableSemanticSynthesizer
from tests.fixtures import FakeSemanticSynthesizer, request_payload, reusable_pattern_output


def test_synthesize_endpoint_returns_validated_pattern() -> None:
    fake = FakeSemanticSynthesizer()
    with TestClient(create_app(Settings(service_name="test"), synthesizer=fake)) as client:
        response = client.post(
            "/synthesize",
            json=request_payload(),
            headers={"X-Request-ID": "request-123"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "PATTERN"
    assert response.headers["X-Request-ID"] == "request-123"
    assert fake.closed is True


def test_provenance_error_is_explicit_422() -> None:
    output = reusable_pattern_output()
    output.pattern.supporting_cases = ("CASE-FRAUD-001", "MADE-UP")  # type: ignore[union-attr]
    with TestClient(
        create_app(Settings(service_name="test"), synthesizer=FakeSemanticSynthesizer(output))
    ) as client:
        response = client.post("/synthesize", json=request_payload())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_supporting_case"


def test_readiness_fails_when_openai_is_unconfigured() -> None:
    with TestClient(
        create_app(
            Settings(service_name="test"),
            synthesizer=UnavailableSemanticSynthesizer("not configured"),
        )
    ) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    assert health.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "synthesizer_unavailable"
