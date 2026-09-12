from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.domain.context import DetectionContext
from app.domain.models import DetectionTrigger, Evidence
from app.policies.models import AnomalyPolicy


def _time(item: Evidence) -> datetime | None:
    value = item.observed_at or item.data.get("occurred_at") or item.data.get("created_at")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _within_latest(items: list[Evidence], window: timedelta, as_of: datetime | None = None) -> list[Evidence]:
    dated = [(item, _time(item)) for item in items]
    valid = [(item, timestamp) for item, timestamp in dated if timestamp is not None]
    if not valid:
        return items
    anchor = as_of or max(timestamp for _, timestamp in valid)
    return [item for item, timestamp in valid if timedelta(0) <= anchor - timestamp < window]


class AnomalyDetector:
    detector_type = "anomaly"

    def __init__(self, policy: AnomalyPolicy, as_of: datetime | None = None) -> None:
        self.policy = policy
        self.as_of = as_of

    async def detect(self, context: DetectionContext) -> list[DetectionTrigger]:
        if context.subject.type == "message":
            # Message content scope has no account-wide rate/diversity checks.
            return []
        triggers: list[DetectionTrigger] = []
        as_of = self.as_of or context.as_of
        triggers.extend(self._payment_churn(context.evidence, as_of))
        triggers.extend(self._login_diversity(context.evidence, as_of))
        triggers.extend(self._burst(context.evidence, "message", "sender_account_id", self.policy.messages_per_hour, "ANOMALY-CHAT-001", as_of))
        triggers.extend(self._burst(context.evidence, "product", "seller_account_id", self.policy.listings_per_hour, "ANOMALY-LISTING-001", as_of))
        triggers.extend(self._dispute_frequency(context.evidence, as_of))
        return triggers

    def _payment_churn(
        self, evidence: list[Evidence], as_of: datetime | None = None
    ) -> list[DetectionTrigger]:
        groups: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            if item.type == "payment_attempt":
                groups[str(item.data.get("transaction_id"))].append(item)
        triggers = []
        for transaction_id, items in groups.items():
            recent = _within_latest(items, timedelta(hours=1), as_of or self.as_of)
            instruments = {item.data.get("payment_instrument_hash") for item in recent}
            instruments.discard(None)
            if len(instruments) >= self.policy.payment_instruments_per_hour:
                triggers.append(
                    DetectionTrigger(
                        type="payment_instrument_churn",
                        detector="anomaly",
                        rule_id="ANOMALY-PAYMENT-001",
                        reason="Multiple payment instruments were used for one transaction within one hour.",
                        raw_result={"transaction_id": transaction_id, "instrument_count": len(instruments)},
                        evidence_refs=[item.id for item in recent],
                    )
                )
        return triggers

    def _login_diversity(
        self, evidence: list[Evidence], as_of: datetime | None = None
    ) -> list[DetectionTrigger]:
        as_of = as_of or self.as_of
        groups: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            if item.type == "login_event" and item.data.get("success", True) and item.data.get("account_id"):
                groups[str(item.data["account_id"])].append(item)
        triggers = []
        for account_id, group in groups.items():
            items = _within_latest(group, timedelta(hours=24), as_of)
            countries = {item.data.get("country_code") for item in items}; countries.discard(None)
            devices = {item.data.get("device_id") for item in items}; devices.discard(None)
            if len(countries) < self.policy.login_countries_per_day and len(devices) < self.policy.login_devices_per_day:
                continue
            triggers.append(DetectionTrigger(
                type="login_diversity_spike",
                detector="anomaly",
                rule_id="ANOMALY-ACCESS-001",
                reason="Login country or device diversity exceeded the 24-hour threshold.",
                raw_result={"account_id": account_id, "country_count": len(countries), "device_count": len(devices)},
                evidence_refs=[item.id for item in items],
            ))
        return triggers

    def _burst(
        self,
        evidence: list[Evidence],
        kind: str,
        group_key: str,
        threshold: int,
        rule_id: str,
        as_of: datetime | None,
    ) -> list[DetectionTrigger]:
        groups: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            if item.type == kind and item.data.get(group_key):
                groups[str(item.data[group_key])].append(item)
        triggers = []
        for group, items in groups.items():
            recent = _within_latest(items, timedelta(hours=1), as_of)
            if len(recent) >= threshold:
                triggers.append(
                    DetectionTrigger(
                        type=f"{kind}_velocity_spike",
                        detector="anomaly",
                        rule_id=rule_id,
                        reason=f"{kind.title()} activity exceeded the one-hour threshold.",
                        raw_result={group_key: group, "count": len(recent), "threshold": threshold},
                        evidence_refs=[item.id for item in recent],
                    )
                )
        return triggers

    def _dispute_frequency(self, evidence: list[Evidence], as_of: datetime | None) -> list[DetectionTrigger]:
        groups: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            if item.type == "dispute" and item.data.get("opened_by_account_id"):
                groups[str(item.data["opened_by_account_id"])].append(item)
        triggers = []
        for account_id, items in groups.items():
            recent = _within_latest(items, timedelta(days=7), as_of)
            if len(recent) >= self.policy.disputes_per_week:
                triggers.append(DetectionTrigger(type="dispute_frequency_spike", detector="anomaly", rule_id="ANOMALY-DISPUTE-001", reason="Weekly dispute volume exceeded the configured threshold.", raw_result={"opened_by_account_id": account_id, "count": len(recent), "threshold": self.policy.disputes_per_week}, evidence_refs=[item.id for item in recent]))
        return triggers
