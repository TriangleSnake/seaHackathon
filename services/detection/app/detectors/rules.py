from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse

from app.domain.context import DetectionContext
from app.domain.models import DetectionTrigger, Evidence
from app.policies.models import RuleBasedPolicy


def _by_type(evidence: list[Evidence], kind: str) -> list[Evidence]:
    return [item for item in evidence if item.type == kind]


def _time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_external_risk_url(value: str, suffixes: tuple[str, ...]) -> bool:
    hostname = (urlparse(value).hostname or "").lower()
    return any(hostname.endswith(suffix.lower()) for suffix in suffixes)


class RuleDetector:
    detector_type = "rule_based"

    def __init__(self, policy: RuleBasedPolicy) -> None:
        self.policy = policy

    async def detect(self, context: DetectionContext) -> list[DetectionTrigger]:
        triggers: list[DetectionTrigger] = []
        triggers.extend(self._reports(context.evidence))
        triggers.extend(self._messages(context.evidence))
        triggers.extend(self._access_change(context.evidence))
        triggers.extend(self._reused_images(context.evidence))
        triggers.extend(self._refund_dispute_overlap(context.evidence))
        triggers.extend(self._delivery_claim_conflict(context.evidence))
        return triggers

    def _reports(self, evidence: list[Evidence]) -> list[DetectionTrigger]:
        rows = [
            item
            for item in _by_type(evidence, "report_record")
            if item.data.get("status") in set(self.policy.active_report_statuses)
        ]
        if not rows:
            return []
        return [
            DetectionTrigger(
                type="active_report",
                detector="rule_based",
                rule_id="RULE-REPORT-001",
                reason="Subject has an active marketplace report.",
                raw_result={"report_count": len(rows)},
                evidence_refs=[item.id for item in rows],
            )
        ]

    def _messages(self, evidence: list[Evidence]) -> list[DetectionTrigger]:
        flagged: list[Evidence] = []
        matches: set[str] = set()
        for item in _by_type(evidence, "message"):
            text = str(item.data.get("text") or "")
            urls = [str(url) for url in item.data.get("urls") or []]
            invalid_url = any(_is_external_risk_url(url, self.policy.risk_domain_suffixes) for url in urls)
            phrase_matches = {phrase for phrase in self.policy.chat_request_phrases if phrase in text}
            negated = any(phrase in text for phrase in self.policy.chat_negations)
            if invalid_url or (phrase_matches and not negated):
                flagged.append(item)
                matches.update(phrase_matches)
                if invalid_url:
                    matches.add("reserved-risk-domain")
        if not flagged:
            return []
        return [
            DetectionTrigger(
                type="suspicious_chat_request",
                detector="rule_based",
                rule_id="RULE-CHAT-001",
                reason="Outbound chat asks for risky off-platform payment or verification action.",
                raw_result={"matches": sorted(matches)},
                evidence_refs=[item.id for item in flagged],
            )
        ]

    def _access_change(self, evidence: list[Evidence]) -> list[DetectionTrigger]:
        security = [
            item
            for item in _by_type(evidence, "account_security_event")
            if item.data.get("event_type") in set(self.policy.sensitive_security_events)
        ]
        logins = [
            item
            for item in _by_type(evidence, "login_event")
            if item.data.get("device_novel") is True and item.data.get("success") is True
        ]
        refs: list[str] = []
        for change in security:
            change_time = change.observed_at or _time(change.data.get("occurred_at"))
            for login in logins:
                if change.data.get("account_id") != login.data.get("account_id"):
                    continue
                login_time = login.observed_at or _time(login.data.get("occurred_at"))
                if change_time and login_time and timedelta(0) <= login_time - change_time <= timedelta(minutes=self.policy.access_window_minutes):
                    refs.extend([change.id, login.id])
        refs = list(dict.fromkeys(refs))
        if not refs:
            return []
        return [
            DetectionTrigger(
                type="security_change_followed_by_novel_login",
                detector="rule_based",
                rule_id="RULE-ACCESS-001",
                reason="A sensitive account change was followed by a novel-device login.",
                evidence_refs=refs,
            )
        ]

    def _reused_images(self, evidence: list[Evidence]) -> list[DetectionTrigger]:
        groups: dict[str, list[Evidence]] = defaultdict(list)
        for item in _by_type(evidence, "product_image"):
            image_hash = str(item.data.get("image_hash") or "")
            if image_hash:
                groups[image_hash].append(item)
        rows = [items for items in groups.values() if len({i.data.get("product_id") for i in items}) >= self.policy.reused_image_min_products]
        if not rows:
            return []
        refs = list(dict.fromkeys(item.id for items in rows for item in items))
        return [
            DetectionTrigger(
                type="reused_listing_image",
                detector="rule_based",
                rule_id="RULE-LISTING-001",
                reason="The same image hash is used by multiple listings in scope.",
                evidence_refs=refs,
            )
        ]

    def _delivery_claim_conflict(self, evidence: list[Evidence]) -> list[DetectionTrigger]:
        delivered: dict[object, list[Evidence]] = defaultdict(list)
        claims: dict[object, list[Evidence]] = defaultdict(list)
        for item in _by_type(evidence, "delivery_event"):
            if item.data.get("status") == "delivered":
                delivered[item.data.get("transaction_id")].append(item)
        for kind in ("refund", "dispute"):
            for item in _by_type(evidence, kind):
                reason = str(item.data.get("reason") or "")
                if any(term in reason for term in self.policy.delivery_claim_terms):
                    claims[item.data.get("transaction_id")].append(item)
        refs: list[str] = []
        for transaction_id in delivered.keys() & claims.keys():
            matching_claims = []
            matching_deliveries = []
            for claim in claims[transaction_id]:
                claim_time = claim.observed_at or _time(
                    claim.data.get("requested_at") or claim.data.get("created_at")
                )
                for delivery in delivered[transaction_id]:
                    delivery_time = delivery.observed_at or _time(
                        delivery.data.get("occurred_at")
                    )
                    if claim_time and delivery_time and claim_time >= delivery_time:
                        matching_claims.append(claim)
                        matching_deliveries.append(delivery)
            refs.extend(item.id for item in matching_deliveries + matching_claims)
        if not refs:
            return []
        return [DetectionTrigger(type="delivered_item_claim_conflict", detector="rule_based", rule_id="RULE-DELIVERY-001", reason="A non-delivery or empty-package claim follows a delivered event.", evidence_refs=list(dict.fromkeys(refs)))]

    def _refund_dispute_overlap(self, evidence: list[Evidence]) -> list[DetectionTrigger]:
        refunds = defaultdict(list)
        disputes = defaultdict(list)
        for item in _by_type(evidence, "refund"):
            refunds[item.data.get("transaction_id")].append(item)
        for item in _by_type(evidence, "dispute"):
            disputes[item.data.get("transaction_id")].append(item)
        refs = [
            item.id
            for transaction_id in refunds.keys() & disputes.keys()
            for item in refunds[transaction_id] + disputes[transaction_id]
        ]
        if not refs:
            return []
        return [
            DetectionTrigger(
                type="refund_dispute_overlap",
                detector="rule_based",
                rule_id="RULE-DISPUTE-001",
                reason="A refund and payment dispute overlap for the same transaction.",
                evidence_refs=list(dict.fromkeys(refs)),
            )
        ]
