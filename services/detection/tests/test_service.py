from __future__ import annotations

import asyncio

from app.domain.context import DetectionContext
from app.domain.models import DetectionRequest, Evidence, Subject
from app.service import DetectionService


class FakeRepository:
    def __init__(self, context: DetectionContext | None) -> None:
        self.context = context

    async def load_context(self, subject: Subject) -> DetectionContext | None:
        return self.context


def evidence(
    evidence_id: str,
    evidence_type: str,
    **data: object,
) -> Evidence:
    return Evidence(
        id=evidence_id,
        source="environment",
        type=evidence_type,
        data=data,
    )


def test_rule_detector_finds_suspicious_outbound_message() -> None:
    subject = Subject(type="account", id="ACC-0101")
    context = DetectionContext(
        subject=subject,
        account_ids=["ACC-0101"],
        evidence=[
            evidence(
                "MSG-0901",
                "message",
                sender_account_id="ACC-0101",
                text="請到驗證頁重新開通，完成後我才能出貨。",
                urls=["https://verify-market.invalid/session"],
            )
        ],
    )
    service = DetectionService(FakeRepository(context))

    result = asyncio.run(service.detect(DetectionRequest(subject=subject)))

    assert result.detected is True
    assert [trigger.rule_id for trigger in result.triggers] == ["RULE-CHAT-001"]
    assert result.triggers[0].evidence_refs == ["MSG-0901"]
    assert result.evidence[0].id == "MSG-0901"


def test_legitimate_warning_is_not_flagged() -> None:
    subject = Subject(type="account", id="ACC-0001")
    context = DetectionContext(
        subject=subject,
        account_ids=["ACC-0001"],
        evidence=[
            evidence(
                "MSG-0007",
                "message",
                sender_account_id="ACC-0001",
                text="銀行轉帳也請使用平台內建付款，不需要私下匯款。",
                urls=[],
            )
        ],
    )
    service = DetectionService(FakeRepository(context))

    result = asyncio.run(service.detect(DetectionRequest(subject=subject)))

    assert result.detected is False
    assert result.triggers == []


def test_anomaly_detector_finds_payment_instrument_churn() -> None:
    subject = Subject(type="transaction", id="TXN-0091")
    context = DetectionContext(
        subject=subject,
        account_ids=["ACC-0091"],
        evidence=[
            evidence(
                "PAY-0901",
                "payment_attempt",
                transaction_id="TXN-0091",
                payment_instrument_hash="one",
                occurred_at="2026-09-04T10:00:00+08:00",
            ),
            evidence(
                "PAY-0902",
                "payment_attempt",
                transaction_id="TXN-0091",
                payment_instrument_hash="two",
                occurred_at="2026-09-04T10:08:00+08:00",
            ),
        ],
    )
    service = DetectionService(FakeRepository(context))

    result = asyncio.run(
        service.detect(
            DetectionRequest(subject=subject, requested_checks=["anomaly"])
        )
    )

    assert result.detected is True
    assert result.triggers[0].detector == "anomaly"
    assert result.triggers[0].rule_id == "ANOMALY-PAYMENT-001"
    assert set(result.triggers[0].evidence_refs) == {"PAY-0901", "PAY-0902"}


def test_requested_checks_filter_detectors() -> None:
    subject = Subject(type="account", id="ACC-0101")
    context = DetectionContext(
        subject=subject,
        account_ids=["ACC-0101"],
        evidence=[
            evidence(
                "RPT-0901",
                "report_record",
                status="open",
                reason="對方要求離開平台驗證付款",
            )
        ],
    )
    service = DetectionService(FakeRepository(context))

    result = asyncio.run(
        service.detect(
            DetectionRequest(subject=subject, requested_checks=["anomaly"])
        )
    )

    assert result.detected is False


def test_explicit_empty_requested_checks_runs_no_detectors() -> None:
    subject = Subject(type="account", id="ACC-0101")
    context = DetectionContext(
        subject=subject,
        account_ids=["ACC-0101"],
        evidence=[evidence("RPT-0901", "report_record", status="open")],
    )
    service = DetectionService(FakeRepository(context))

    result = asyncio.run(
        service.detect(DetectionRequest(subject=subject, requested_checks=[]))
    )

    assert result.detected is False
    assert result.triggers == []


def test_only_referenced_evidence_is_returned() -> None:
    subject = Subject(type="account", id="ACC-0101")
    context = DetectionContext(
        subject=subject,
        account_ids=["ACC-0101"],
        evidence=[
            evidence("RPT-0901", "report_record", status="open", reason="可疑連結"),
            evidence("LOG-0001", "login_event", ip_address="192.0.2.1"),
        ],
    )
    service = DetectionService(FakeRepository(context))

    result = asyncio.run(service.detect(DetectionRequest(subject=subject)))

    assert [item.id for item in result.evidence] == ["RPT-0901"]


def test_llm_check_uses_classifier_threshold_result() -> None:
    class ConfidentClassifier:
        async def classify(self, messages: list[str], threshold: float):
            from app.detectors.llm import LLMClassification

            assert threshold == 0.6
            return LLMClassification(
                suspicious=True,
                raw_result={
                    "label": True,
                    "probabilities": {"true": 0.91, "false": 0.09},
                    "threshold": threshold,
                },
            )

    subject = Subject(type="message", id="MSG-0901")
    context = DetectionContext(
        subject=subject,
        account_ids=["ACC-0101"],
        evidence=[evidence("MSG-0901", "message", text="請到外部頁面驗證")],
    )
    service = DetectionService(FakeRepository(context), classifier=ConfidentClassifier())

    result = asyncio.run(
        service.detect(
            DetectionRequest(subject=subject, requested_checks=["llm_classifier"])
        )
    )

    assert result.detected is True
    assert result.triggers[0].raw_result["probabilities"]["true"] == 0.91


def test_baseline_and_candidate_policies_are_selected_independently() -> None:
    subject = Subject(type="account", id="ACC-0001")
    context = DetectionContext(
        subject=subject,
        account_ids=["ACC-0001"],
        evidence=[evidence("RPT-0001", "report_record", status="open")]
        + [
            evidence(
                f"PROD-{number:04d}",
                "product",
                seller_account_id="ACC-0001",
                created_at=f"2026-09-01T10:{number:02d}:00+08:00",
            )
            for number in range(4)
        ],
    )
    service = DetectionService(FakeRepository(context))

    baseline = asyncio.run(
        service.detect(
            DetectionRequest(
                subject=subject,
                requested_checks=["anomaly"],
                policy_ref={"type": "detection", "version": "baseline-v1"},
            )
        )
    )
    candidate = asyncio.run(
        service.detect(
            DetectionRequest(
                subject=subject,
                requested_checks=["anomaly"],
                policy_ref={"type": "detection", "version": "candidate-v1"},
            )
        )
    )
    default_after_candidate = asyncio.run(
        service.detect(DetectionRequest(subject=subject))
    )

    assert baseline.detected is False
    assert candidate.detected is True
    assert candidate.triggers[0].raw_result["policy_version"] == "candidate-v1"
    assert {
        trigger.raw_result["policy_version"]
        for trigger in default_after_candidate.triggers
    } == {"baseline-v1"}


def test_delivery_claim_before_delivery_does_not_trigger() -> None:
    subject = Subject(type="transaction", id="TXN-0001")
    context = DetectionContext(
        subject=subject,
        evidence=[
            Evidence(
                id="REF-0001",
                source="environment",
                type="refund",
                observed_at="2026-09-01T10:00:00+08:00",
                data={"transaction_id": "TXN-0001", "reason": "未收到商品"},
            ),
            Evidence(
                id="DEL-0001",
                source="environment",
                type="delivery_event",
                observed_at="2026-09-01T12:00:00+08:00",
                data={"transaction_id": "TXN-0001", "status": "delivered"},
            ),
        ],
    )
    service = DetectionService(FakeRepository(context))

    result = asyncio.run(
        service.detect(
            DetectionRequest(subject=subject, requested_checks=["rule_based"])
        )
    )

    assert result.detected is False
