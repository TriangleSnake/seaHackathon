from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from app.adapters import collect_investigation_results, deterministic_case_id
from app.clients import PipelineClients
from app.contracts import ContractValidator
from app.models import PatrolRequest
from app.orchestrator import DiscoveryPipelineOrchestrator
from app.settings import Settings


ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "shared" / "schemas"


def patrol_request(run_id: str = "run-001") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "mode": "manual",
        "strategy": "exploit",
        "scope": {"subject_types": ["account"]},
    }


def discovery(subject_id: str, suffix: str = "1") -> dict[str, Any]:
    return {
        "subject": {"type": "account", "id": subject_id},
        "hypothesis": "coordinated account abuse",
        "reason": "shared infrastructure",
        "observed_signals": [
            {
                "name": "shared_device",
                "description": "Account shares a device with suspicious peers",
                "evidence_refs": [f"E-{suffix}-device"],
            }
        ],
        "counter_signals": [],
        "priority": 0.9,
        "evidence_refs": [
            f"E-{suffix}-device",
            f"E-{suffix}-ip",
            f"E-{suffix}-payment",
            f"E-{suffix}-image",
        ],
    }


def patrol_result(discoveries: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    for index, _ in enumerate(discoveries, 1):
        evidence.extend(
            [
                {
                    "id": f"E-{index}-device",
                    "source": "environment",
                    "type": "login",
                    "data": {"device_id": f"DEV-{index}"},
                },
                {
                    "id": f"E-{index}-ip",
                    "source": "environment",
                    "type": "login",
                    "data": {"ip_address": f"192.0.2.{index}"},
                },
                {
                    "id": f"E-{index}-payment",
                    "source": "environment",
                    "type": "payment",
                    "data": {"payment_instrument_hash": f"pay-hash-{index}"},
                },
                {
                    "id": f"E-{index}-image",
                    "source": "environment",
                    "type": "product_image",
                    "data": {"image_hash": f"image-hash-{index}"},
                },
            ]
        )
    return {
        "run_id": "run-001",
        "strategy": "exploit",
        "policy_ref": {"id": "patrol-exploit", "version": "v1"},
        "discoveries": discoveries,
        "evidence": evidence,
    }


def association_result(
    request: dict[str, Any], *, with_related: bool = True, with_evidence: bool = True
) -> dict[str, Any]:
    subject = request["subject"]
    related_id = f"{subject['id']}-related"
    evidence = (
        [
            {
                "id": f"A-{subject['id']}",
                "source": "association",
                "type": "shared_device",
                "data": {"device_id": "DEV-related"},
            }
        ]
        if with_evidence
        else []
    )
    related = (
        [
            {
                "subject": {"type": "account", "id": related_id},
                "association_score": 0.8,
                "reason": "shared device",
                "relation_paths": [
                    {
                        "nodes": [subject["id"], related_id],
                        "edge_types": ["shared_device"],
                        "evidence_refs": [evidence[0]["id"]],
                    }
                ],
                "evidence_refs": [evidence[0]["id"]],
            }
        ]
        if with_related
        else []
    )
    edges = (
        [
            {
                "source": subject["id"],
                "target": related_id,
                "type": "shared_device",
                "relationship": "observed",
                "confidence": 1,
                "evidence_refs": [evidence[0]["id"]],
            }
        ]
        if with_related
        else []
    )
    nodes = [{"id": subject["id"], "type": subject["type"]}]
    if with_related:
        nodes.append({"id": related_id, "type": "account"})
    return {
        "case_id": request["case_id"],
        "strategy": "focused",
        "policy_ref": {"id": "association-focused", "version": "v1"},
        "nodes": nodes,
        "edges": edges,
        "related_subjects": related,
        "evidence": evidence,
    }


def investigation_result(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": request["case_id"],
        "subject": request["detection_result"]["subject"],
        "verdict": "suspicious",
        "confidence": 0.75,
        "summary": "Evidence requires review",
        "findings": [],
        "evidence": [
            *request["detection_result"]["evidence"],
            *request.get("existing_evidence", []),
        ],
        "agents_invoked": [],
        "agent_results": [],
        "scoreboard": {
            "status": "stopped",
            "config_ref": request["scoreboard_config_ref"],
            "scoring_policy_version": "test-v1",
            "fraud_score": 0.75,
            "usage": {
                "agent_calls": 0,
                "tool_calls": 0,
                "investigation_steps": 0,
                "tokens": 0,
                "cost_usd": 0,
            },
            "budget": {
                "max_agent_calls": 3,
                "max_tool_calls": 10,
                "max_investigation_steps": 3,
                "max_tokens": 4000,
                "max_cost_usd": 1,
            },
            "agent_usage": [],
            "stop_reason": "insufficient_evidence",
            "updated_at": "2026-09-12T00:00:00Z",
        },
        "stop_reason": "insufficient_evidence",
    }


class FakeServices:
    def __init__(
        self,
        patrol: dict[str, Any],
        association_factory: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        investigation_factory: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        association_status: int = 200,
        investigation_status: int = 200,
    ) -> None:
        self.patrol_result = patrol
        self.association_factory = association_factory or association_result
        self.investigation_factory = investigation_factory or investigation_result
        self.association_status = association_status
        self.investigation_status = investigation_status
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.headers: list[tuple[str, httpx.Headers]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.calls.append((request.url.path, payload))
        self.headers.append((request.url.path, request.headers))
        if request.url.path == "/patrol/run":
            return httpx.Response(200, json=self.patrol_result)
        if request.url.path == "/associate":
            if self.association_status != 200:
                return httpx.Response(self.association_status, json={"error": "unavailable"})
            return httpx.Response(200, json=self.association_factory(payload))
        if request.url.path == "/investigate":
            if self.investigation_status != 200:
                return httpx.Response(self.investigation_status, json={"error": "failed"})
            return httpx.Response(200, json=self.investigation_factory(payload))
        return httpx.Response(404)


def run_pipeline(fake: FakeServices):
    settings = Settings(
        patrol_url="http://patrol.test",
        association_url="http://association.test",
        investigation_url="http://investigation.test",
        timeout_seconds=1,
        scoreboard_config_version="development-v1",
        schema_dir=SCHEMAS,
    )
    clients = PipelineClients.build(settings, httpx.MockTransport(fake))
    orchestrator = DiscoveryPipelineOrchestrator(clients, settings)

    async def run():
        try:
            return await orchestrator.run(PatrolRequest.model_validate(patrol_request()))
        finally:
            await orchestrator.close()

    return asyncio.run(run())


def test_one_discovery_calls_association_then_investigation() -> None:
    fake = FakeServices(patrol_result([discovery("ACC-1")]))
    result = run_pipeline(fake)

    assert result.status == "succeeded"
    assert [path for path, _ in fake.calls] == [
        "/patrol/run",
        "/associate",
        "/investigate",
    ]
    item = result.discoveries[0]
    assert item.association.status == "succeeded"
    assert item.investigation.status == "succeeded"
    assert collect_investigation_results(result)[0].case_id == item.case_id
    patrol_headers = next(headers for path, headers in fake.headers if path == "/patrol/run")
    assert patrol_headers["X-Upstream-Orchestration"] == "association-first"


def test_multiple_discoveries_have_independent_deterministic_lineage() -> None:
    fake = FakeServices(
        patrol_result([discovery("ACC-1", "1"), discovery("ACC-2", "2")])
    )
    result = run_pipeline(fake)

    case_ids = [item.case_id for item in result.discoveries]
    assert len(set(case_ids)) == 2
    assert case_ids == [
        deterministic_case_id(result.patrol.result, item.patrol_discovery)
        for item in result.discoveries
    ]
    downstream = [payload["case_id"] for path, payload in fake.calls if path != "/patrol/run"]
    assert downstream == [case_ids[0], case_ids[0], case_ids[1], case_ids[1]]


def test_association_evidence_reaches_investigation_and_seeds_are_canonical() -> None:
    fake = FakeServices(patrol_result([discovery("ACC-1")]))
    result = run_pipeline(fake)
    association_payload = next(payload for path, payload in fake.calls if path == "/associate")
    investigation_payload = next(
        payload for path, payload in fake.calls if path == "/investigate"
    )

    assert result.status == "succeeded"
    assert {item["type"] for item in association_payload["seed_indicators"]} == {
        "device",
        "ip",
        "payment_account",
    }
    assert all(item["value"] != "image-hash-1" for item in association_payload["seed_indicators"])
    assert [item["id"] for item in investigation_payload["existing_evidence"]] == ["A-ACC-1"]
    assert [item["id"] for item in investigation_payload["detection_result"]["evidence"]] == [
        "E-1-device",
        "E-1-ip",
        "E-1-payment",
        "E-1-image",
    ]


def test_empty_valid_association_still_investigates_with_patrol_evidence() -> None:
    fake = FakeServices(
        patrol_result([discovery("ACC-1")]),
        association_factory=lambda request: association_result(
            request, with_related=False, with_evidence=False
        ),
    )
    result = run_pipeline(fake)
    investigation_payload = next(
        payload for path, payload in fake.calls if path == "/investigate"
    )

    assert result.status == "succeeded"
    assert investigation_payload["existing_evidence"] == []
    assert investigation_payload["detection_result"]["evidence"]


def test_association_failure_is_explicit_and_skips_investigation() -> None:
    fake = FakeServices(patrol_result([discovery("ACC-1")]), association_status=503)
    result = run_pipeline(fake)

    assert result.status == "failed"
    assert result.discoveries[0].association.status == "failed"
    assert result.discoveries[0].association.error.kind == "http_status"
    assert result.discoveries[0].investigation.status == "skipped"
    assert [path for path, _ in fake.calls] == ["/patrol/run", "/associate"]


def test_investigation_failure_is_explicit() -> None:
    fake = FakeServices(patrol_result([discovery("ACC-1")]), investigation_status=502)
    result = run_pipeline(fake)

    assert result.status == "failed"
    assert result.discoveries[0].association.status == "succeeded"
    assert result.discoveries[0].investigation.status == "failed"
    assert result.discoveries[0].investigation.error.kind == "http_status"


@pytest.mark.parametrize("mismatch", ["association_case", "investigation_subject"])
def test_case_or_subject_mismatch_is_rejected(mismatch: str) -> None:
    if mismatch == "association_case":
        def bad_association(request: dict[str, Any]) -> dict[str, Any]:
            result = association_result(request)
            result["case_id"] = "wrong-case"
            return result

        fake = FakeServices(
            patrol_result([discovery("ACC-1")]), association_factory=bad_association
        )
    else:
        def bad_investigation(request: dict[str, Any]) -> dict[str, Any]:
            result = investigation_result(request)
            result["subject"] = {"type": "account", "id": "wrong-subject"}
            return result

        fake = FakeServices(
            patrol_result([discovery("ACC-1")]),
            investigation_factory=bad_investigation,
        )

    result = run_pipeline(fake)
    failed_stage = (
        result.discoveries[0].association
        if mismatch == "association_case"
        else result.discoveries[0].investigation
    )
    assert failed_stage.status == "failed"
    assert failed_stage.error.kind == "lineage_mismatch"


def test_no_discoveries_is_successful_and_has_no_downstream_calls() -> None:
    fake = FakeServices(patrol_result([]))
    result = run_pipeline(fake)

    assert result.status == "succeeded"
    assert result.discoveries == []
    assert [path for path, _ in fake.calls] == ["/patrol/run"]


def test_all_generated_payloads_satisfy_current_shared_contracts() -> None:
    fake = FakeServices(patrol_result([discovery("ACC-1")]))
    result = run_pipeline(fake)
    assert result.status == "succeeded"
    contracts = ContractValidator(SCHEMAS)
    validators = {
        "/patrol/run": contracts.patrol_request,
        "/associate": contracts.association_request,
        "/investigate": contracts.investigation_request,
    }
    for path, payload in fake.calls:
        validators[path](payload)


def test_partial_failure_continues_remaining_discoveries() -> None:
    calls = 0

    def sometimes_fails(request: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        result = association_result(request)
        if calls == 1:
            result["case_id"] = "wrong-case"
        return result

    fake = FakeServices(
        patrol_result([discovery("ACC-1", "1"), discovery("ACC-2", "2")]),
        association_factory=sometimes_fails,
    )
    result = run_pipeline(fake)

    assert result.status == "partial_failure"
    assert [item.investigation.status for item in result.discoveries] == [
        "skipped",
        "succeeded",
    ]


def test_schema_invalid_association_response_is_explicit() -> None:
    def invalid_association(request: dict[str, Any]) -> dict[str, Any]:
        result = association_result(request)
        result["unsupported"] = True
        return result

    fake = FakeServices(
        patrol_result([discovery("ACC-1")]),
        association_factory=invalid_association,
    )
    result = run_pipeline(fake)

    assert result.discoveries[0].association.status == "failed"
    assert result.discoveries[0].association.error.kind == "contract_invalid"
    assert result.discoveries[0].investigation.status == "skipped"
