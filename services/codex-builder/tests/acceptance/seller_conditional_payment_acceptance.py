from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import sqlite3
import pytest


DETECTION_ROOT = Path(
    os.environ.get(
        "DETECTION_CANDIDATE_ROOT",
        str(Path(__file__).resolve().parents[3] / "detection"),
    )
).resolve()
if str(DETECTION_ROOT) not in sys.path:
    sys.path.insert(0, str(DETECTION_ROOT))

from app.detectors.rules import RuleDetector
from app.domain.context import DetectionContext
from app.domain.models import Evidence, Subject
from app.policies.repository import FilePolicyRepository
from app.repository import PostgresDetectionRepository


NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)
POLICY = FilePolicyRepository(DETECTION_ROOT / "config" / "policies").resolve(
    "baseline-v1"
)


def _message(identifier: str, text: str, role: str) -> Evidence:
    return Evidence(
        id=identifier,
        source="environment",
        type="message",
        observed_at=NOW,
        data={
            "conversation_id": "CONV-CODE-ACCEPTANCE",
            "sender_account_id": f"ACC-{role.upper()}",
            "recipient_account_id": "ACC-OTHER",
            "sender_role": role,
            "text": text,
            "urls": [],
        },
    )


def _detect(*messages: Evidence) -> list:
    context = DetectionContext(
        subject=Subject(type="message", id=messages[0].id),
        account_ids=["ACC-SELLER", "ACC-BUYER"],
        evidence=list(messages),
        as_of=NOW,
    )
    return asyncio.run(RuleDetector(POLICY.rule_based).detect(context))


def test_seller_payment_and_extreme_discount_triggers() -> None:
    triggers = _detect(
        _message("TARGET", "這台相機今天付款，價格就再便宜一半。", "seller")
    )

    assert triggers
    assert any(trigger.evidence_refs == ["TARGET"] for trigger in triggers)


def test_seller_payment_only_remains_clean() -> None:
    assert _detect(_message("TARGET", "商品確認後請完成付款。", "seller")) == []


def test_seller_payment_and_urgency_triggers() -> None:
    assert _detect(_message("TARGET", "請在十分鐘內付款，優惠只保留十分鐘。", "seller"))


def test_seller_inducement_only_remains_clean() -> None:
    assert _detect(_message("TARGET", "這件商品可以再便宜一半。", "seller")) == []


def test_buyer_payment_and_inducement_remains_clean() -> None:
    assert (
        _detect(
            _message("TARGET", "如果今天付款，可以再便宜一半嗎？", "buyer")
        )
        == []
    )


def test_negated_safety_payment_language_remains_clean() -> None:
    assert (
        _detect(
            _message(
                "TARGET",
                "不需要私下付款，就算有人說可以便宜一半也不要。",
                "seller",
            )
        )
        == []
    )


@pytest.mark.parametrize("role,joined,expected", [
    ("seller", "2026-09-01", "seller"), ("buyer", "2026-09-01", "buyer"),
    ("support", "2026-09-01", "support"), (None, "2026-09-01", None),
    ("seller", "2026-09-11", None),
])
def test_repository_exposes_target_message_sender_role(role, joined, expected) -> None:
    # Execute candidate SQL against a label-free relational fixture, without
    # inspecting its implementation technique to decide whether it passes.
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE visible_messages(id, conversation_id, sender_account_id,
        recipient_account_id, text, urls, created_at);
      CREATE TABLE conversations(id, transaction_id, shop_id);
      CREATE TABLE transactions(id, product_id);
      CREATE TABLE conversation_participants(conversation_id, account_id, participant_role, joined_at);
      INSERT INTO conversations VALUES('C', NULL, NULL);
      INSERT INTO visible_messages VALUES('TARGET','C','S','B','hello','[]','2026-09-10');
      INSERT INTO visible_messages VALUES('OTHER','C','B','S','other','[]','2026-09-10');
      INSERT INTO conversation_participants VALUES('OTHER-CONVERSATION','S','seller','2026-09-01');
      INSERT INTO conversation_participants VALUES('C','B','buyer','2026-09-01');
    ''')
    if role:
        db.execute("INSERT INTO conversation_participants VALUES('C','S',?,?)", (role, joined))

    async def run() -> Evidence:
        repository = PostgresDetectionRepository.__new__(PostgresDetectionRepository)

        async def fetch(query: str, params: tuple = ()) -> list[dict]:
            rows = [dict(row) for row in db.execute(query.replace('%s', '?'), params)]
            for row in rows:
                row.update(created_at=NOW, urls=[])
            return rows

        repository._fetch_all = fetch
        rows = await repository._load_messages(
            Subject(type="message", id="TARGET"), ["ACC-SELLER", "ACC-BUYER"]
        )
        assert [row.id for row in rows] == ["TARGET"]
        return rows[0]

    evidence = asyncio.run(run())

    db.close()
    assert evidence.data.get("sender_role") == expected


def test_compound_signals_are_not_combined_across_messages() -> None:
    assert (
        _detect(
            _message("TARGET", "商品確認後請完成付款。", "seller"),
            _message("OTHER", "這件商品可以再便宜一半。", "seller"),
        )
        == []
    )
