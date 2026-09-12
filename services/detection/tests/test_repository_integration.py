from __future__ import annotations

import asyncio
import os

import psycopg
import pytest
from datetime import datetime

from app.domain.models import DetectionRequest, Subject
from app.repository import PostgresDetectionRepository
from app.service import DetectionService, SubjectNotFoundError
from app.detectors.rules import RuleDetector
from app.policies.repository import FilePolicyRepository


DATABASE_URL = os.environ.get("DETECTION_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="integration database not configured")


async def _set_simulation_time(value: str) -> None:
    assert DATABASE_URL
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        await connection.execute("SELECT set_simulation_time(%s)", (value,))


async def _reset_simulation() -> None:
    assert DATABASE_URL
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        await connection.execute("SELECT reset_simulation()")


async def _simulation_time() -> str:
    assert DATABASE_URL
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        row = await (await connection.execute(
            "SELECT simulation_time::text FROM simulation_state WHERE singleton_id = 1"
        )).fetchone()
        assert row
        return str(row[0])


async def _exercise_seed() -> None:
    assert DATABASE_URL
    repository = PostgresDetectionRepository(DATABASE_URL, pool_size=2)
    service = DetectionService(repository)
    previous_time = await _simulation_time()
    try:
        assert await repository.health() is True
        await _reset_simulation()
        with pytest.raises(SubjectNotFoundError):
            await service.detect(
                DetectionRequest(subject=Subject(type="message", id="MSG-0901"))
            )
        pre_event_product = await service.detect(
            DetectionRequest(
                subject=Subject(type="product", id="PROD-0081"),
                requested_checks=["rule_based"],
            )
        )
        assert "RULE-LISTING-001" not in {
            trigger.rule_id for trigger in pre_event_product.triggers
        }

        await _set_simulation_time("2026-09-10 12:00:00+08")
        message_result = await service.detect(
            DetectionRequest(
                subject=Subject(type="message", id="MSG-0901"),
                policy_ref={"type": "detection", "version": "baseline-v1"},
            )
        )
        candidate_message_result = await service.detect(
            DetectionRequest(
                subject=Subject(type="message", id="MSG-0901"),
                policy_ref={"type": "detection", "version": "candidate-v1"},
            )
        )
        payment_result = await service.detect(
            DetectionRequest(
                subject=Subject(type="transaction", id="TXN-0091"),
                requested_checks=["anomaly"],
            )
        )
        product_result = await service.detect(
            DetectionRequest(
                subject=Subject(type="product", id="PROD-0081"),
                requested_checks=["rule_based"],
            )
        )
        delivery_result = await service.detect(
            DetectionRequest(
                subject=Subject(type="transaction", id="TXN-0093"),
                requested_checks=["rule_based"],
            )
        )

        assert "RULE-CHAT-001" in {trigger.rule_id for trigger in message_result.triggers}
        assert {
            trigger.raw_result["policy_version"]
            for trigger in message_result.triggers
        } == {"baseline-v1"}
        assert {
            trigger.raw_result["policy_version"]
            for trigger in candidate_message_result.triggers
        } == {"candidate-v1"}
        # Sept 4 payment events have expired by Sept 10.
        assert "ANOMALY-PAYMENT-001" not in {
            trigger.rule_id for trigger in payment_result.triggers
        }
        assert "RULE-LISTING-001" in {
            trigger.rule_id for trigger in product_result.triggers
        }
        assert "RULE-DELIVERY-001" in {
            trigger.rule_id for trigger in delivery_result.triggers
        }
    finally:
        await _set_simulation_time(previous_time)
        await repository.close()


def test_detection_against_replayable_environment_seed() -> None:
    asyncio.run(_exercise_seed())


def test_context_keeps_snapshot_when_clock_changes_mid_query():
    async def run():
        repository = PostgresDetectionRepository(DATABASE_URL, pool_size=2)
        previous = await _simulation_time()
        original = repository._load_messages
        async def change_clock(subject, account_ids):
            rows = await original(subject, account_ids)
            await _set_simulation_time('2026-09-10T12:00:00+08:00')
            return rows
        try:
            await _reset_simulation()
            repository._load_messages = change_clock
            context = await repository.load_context(Subject(type='product', id='PROD-0081'))
            assert context is not None
            assert all(e.observed_at is None or e.observed_at <= context.as_of for e in context.evidence)
            assert context.as_of == datetime.fromisoformat('2026-09-01T00:00:00+08:00')
            policy = FilePolicyRepository('config/policies').resolve('baseline-v1')
            assert 'RULE-LISTING-001' not in {t.rule_id for t in await RuleDetector(policy.rule_based).detect(context)}
        finally:
            await _set_simulation_time(previous)
            await repository.close()
    asyncio.run(run())
