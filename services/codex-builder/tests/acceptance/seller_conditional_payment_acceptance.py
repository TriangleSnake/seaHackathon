from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys


DETECTION_ROOT = Path(__file__).resolve().parents[3] / "detection"
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
        _message("TARGET", "照片就是實品，今天付款可以再便宜一半。", "seller")
    )

    assert triggers
    assert any(trigger.evidence_refs == ["TARGET"] for trigger in triggers)


def test_seller_payment_only_remains_clean() -> None:
    assert _detect(_message("TARGET", "商品確認後請完成付款。", "seller")) == []


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


def test_repository_exposes_target_message_sender_role() -> None:
    queries: list[str] = []

    async def run() -> Evidence:
        repository = PostgresDetectionRepository.__new__(PostgresDetectionRepository)

        async def fetch(query: str, params: tuple = ()) -> list[dict]:
            del params
            queries.append(query)
            normalized = " ".join(query.split()).lower()
            row = {
                "id": "TARGET",
                "conversation_id": "CONV-CODE-ACCEPTANCE",
                "sender_account_id": "ACC-SELLER",
                "recipient_account_id": "ACC-BUYER",
                "text": "今天付款可以再便宜一半",
                "urls": [],
                "created_at": NOW,
            }
            if "participant_role" in normalized and "sender_role" in normalized:
                row["sender_role"] = "seller"
            return [row]

        repository._fetch_all = fetch
        rows = await repository._load_messages(
            Subject(type="message", id="TARGET"), ["ACC-SELLER", "ACC-BUYER"]
        )
        return rows[0]

    evidence = asyncio.run(run())

    assert any("conversation_participants" in query.lower() for query in queries)
    assert evidence.data["sender_role"] == "seller"


def test_compound_signals_are_not_combined_across_messages() -> None:
    assert (
        _detect(
            _message("TARGET", "商品確認後請完成付款。", "seller"),
            _message("OTHER", "這件商品可以再便宜一半。", "seller"),
        )
        == []
    )
