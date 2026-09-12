"""Failure policies must preserve component outcomes and safe HTTP errors."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.detectors.registry import RegisteredDetector
from app.domain.context import DetectionContext
from app.domain.models import DetectionRequest, Evidence, Subject
from app.errors import CheckInconclusiveError
from app.main import create_app
from app.policies.models import DetectionPolicy
from app.policies.repository import FilePolicyRepository
from app.service import DetectionService
from app.settings import Settings


NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)
PRIVATE_ERROR = "upstream credential=private-test-token"


class ReportRepository:
    async def load_context(self, subject, required_evidence=None):
        return DetectionContext(
            subject=subject,
            as_of=NOW,
            evidence=[Evidence(
                id="report-1", source="environment", type="report_record",
                observed_at=NOW, data={"status": "open"},
            )],
        )

    async def close(self):
        pass


def component_policy(failure_mode, version="broken-v1"):
    document = FilePolicyRepository("config/policies").resolve("baseline-v1").model_dump(mode="json")
    document.update(version="failure-test-v1", components=[
        {"id": "broken", "type": "anomaly", "version": version, "failure_mode": failure_mode},
        {"id": "rules", "type": "rule_based", "version": "builtin-v1"},
    ])
    return DetectionPolicy.model_validate(document)


def register_failure(service, phase, error):
    class BrokenDetector:
        async def detect(self, context):
            raise error

    def factory(config):
        if phase == "factory":
            raise error
        return BrokenDetector()

    service.registry.register(RegisteredDetector(
        "anomaly", "broken-v1", frozenset(), factory,
    ))


@pytest.mark.parametrize("phase", ["factory", "detect"])
def test_continue_keeps_failed_status_and_other_component_triggers(phase):
    service = DetectionService(ReportRepository())
    register_failure(service, phase, OSError(PRIVATE_ERROR))

    result = asyncio.run(service.detect(
        DetectionRequest(subject=Subject(type="account", id="A")),
        policy_override=component_policy("continue"),
    ))

    assert result.detected is True
    assert [item.status for item in result.component_results] == ["failed", "completed"]
    assert [item.trigger_count for item in result.component_results] == [0, 1]
    assert result.component_results[0].reason == "OSError"
    assert [item.rule_id for item in result.triggers] == ["RULE-REPORT-001"]
    assert [item.id for item in result.evidence] == ["report-1"]
    assert PRIVATE_ERROR not in result.model_dump_json()


@pytest.mark.parametrize("phase", ["factory", "detect"])
def test_fail_propagates_component_exceptions_instead_of_returning_a_result(phase):
    service = DetectionService(ReportRepository())
    register_failure(service, phase, OSError(PRIVATE_ERROR))

    with pytest.raises(OSError):
        asyncio.run(service.detect(
            DetectionRequest(subject=Subject(type="account", id="A")),
            policy_override=component_policy("fail"),
        ))


def make_app(policy, tmp_path):
    (tmp_path / f"{policy.version}.json").write_text(policy.model_dump_json())
    app = create_app(
        settings=Settings(
            service_name="test-detection", database_url="postgresql://unused",
            database_pool_size=1, openai_api_key=None, openai_model="unused",
        ),
        repository=ReportRepository(),
    )
    app.state.detection_service.policy_repository = FilePolicyRepository(tmp_path)
    return app


def request_body(endpoint, policy):
    request = {
        "subject": {"type": "account", "id": "A"},
        "policy_ref": {"type": "detection", "version": policy.version},
    }
    if endpoint == "/policies/detection/test":
        return {"policy": policy.model_dump(mode="json"), "request": request}
    return request


@pytest.mark.parametrize("endpoint", ["/detect", "/policies/detection/test"])
def test_missing_component_fail_returns_typed_http_error_with_version(endpoint, tmp_path):
    policy = component_policy("fail", version="not-installed-v9")
    with TestClient(make_app(policy, tmp_path), raise_server_exceptions=False) as client:
        response = client.post(endpoint, json=request_body(endpoint, policy), headers={"X-Request-ID": "failure-request"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "check_unavailable"
    assert "not-installed-v9" in error["message"]
    assert error["request_id"] == "failure-request"
    assert "detected" not in response.json()


@pytest.mark.parametrize("endpoint", ["/detect", "/policies/detection/test"])
@pytest.mark.parametrize("error,status_code,code", [
    (OSError(PRIVATE_ERROR), 503, "dependency_unavailable"),
    (CheckInconclusiveError("no usable classification"), 422, "check_inconclusive"),
])
def test_fail_policy_http_errors_keep_typed_status_without_dependency_details(endpoint, error, status_code, code, tmp_path):
    policy = component_policy("fail")
    app = make_app(policy, tmp_path)
    register_failure(app.state.detection_service, "detect", error)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(endpoint, json=request_body(endpoint, policy), headers={"X-Request-ID": "failure-request"})

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == "failure-request"
    assert PRIVATE_ERROR not in response.text
    assert "detected" not in response.json()


def test_absent_snapshot_time_is_null_without_dropping_working_triggers():
    class LegacyRepository:
        async def load_context(self, subject):
            context = await ReportRepository().load_context(subject)
            return SimpleNamespace(
                subject=subject, account_ids=context.account_ids,
                evidence=context.evidence, conversation_context=context.conversation_context,
            )

    result = asyncio.run(DetectionService(LegacyRepository()).detect(
        DetectionRequest(subject=Subject(type="account", id="A"), requested_checks=["rule_based"]),
    ))

    assert result.detected is True
    assert result.triggers[0].raw_result["as_of"] is None
    assert result.triggers[0].raw_result["policy_version"] == "baseline-v1"
