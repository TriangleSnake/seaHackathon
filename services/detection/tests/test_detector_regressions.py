"""Regression contracts for time boundaries and component execution failures."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.detectors.anomaly import _within_latest
from app.domain.context import DetectionContext
from app.domain.models import DetectionRequest, Evidence, Subject
from app.errors import CheckUnavailableError
from app.policies.models import DetectionPolicy
from app.policies.repository import FilePolicyRepository
from app.service import DetectionService


NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


class FixedRepository:
    async def load_context(self, subject, required_evidence=None):
        return DetectionContext(
            subject=subject, as_of=NOW,
            evidence=[Evidence(id="report-1", source="environment", type="report_record",
                               observed_at=NOW - timedelta(hours=1), data={"status": "open"})],
        )


def policy_with_missing_component(mode):
    document = FilePolicyRepository("config/policies").resolve("baseline-v1").model_dump(mode="json")
    document["components"] = [
        {"id": "missing", "type": "anomaly", "version": "not-installed", "failure_mode": mode},
        {"id": "rules", "type": "rule_based", "version": "builtin-v1"},
    ]
    return DetectionPolicy.model_validate(document)


@pytest.mark.parametrize("timestamp", [None, "invalid-date"])
def test_all_undated_events_are_excluded(timestamp):
    rows = [Evidence(id="event", source="environment", type="message",
                     data={"created_at": timestamp})]
    assert _within_latest(rows, timedelta(hours=1), NOW) == []


def test_missing_component_with_fail_policy_aborts_detection():
    with pytest.raises(CheckUnavailableError, match="not-installed"):
        asyncio.run(DetectionService(FixedRepository()).detect(
            DetectionRequest(subject=Subject(type="account", id="A")),
            policy_override=policy_with_missing_component("fail"),
        ))


def test_missing_component_with_continue_policy_preserves_status_and_working_triggers():
    result = asyncio.run(DetectionService(FixedRepository()).detect(
        DetectionRequest(subject=Subject(type="account", id="A")),
        policy_override=policy_with_missing_component("continue"),
    ))
    assert result.detected is True
    assert [item.status for item in result.component_results] == ["unavailable", "completed"]
    assert [item.rule_id for item in result.triggers] == ["RULE-REPORT-001"]


def test_trigger_records_the_snapshot_time_not_wall_clock():
    result = asyncio.run(DetectionService(FixedRepository()).detect(
        DetectionRequest(subject=Subject(type="account", id="A")),
    ))
    assert result.triggers[0].raw_result["as_of"] == "2026-09-10T00:00:00+00:00"
    assert result.triggers[0].raw_result["policy_version"] == "baseline-v1"
