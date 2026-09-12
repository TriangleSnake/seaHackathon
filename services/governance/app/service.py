"""Application service for policy evaluation, explicit review, and auditing."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from uuid import uuid4

from .core.checks import GovernanceCheck
from .core.engine import GovernancePolicyEngine
from .domain.models import (
    GovernanceAuditEvent,
    GovernanceContext,
    GovernancePolicyConfig,
    GovernanceRequest,
    GovernanceResult,
    HumanReviewDecision,
    HumanReviewInput,
)
from .repositories import (
    AuditRepository,
    HumanReviewRepository,
    InMemoryAuditRepository,
    InMemoryHumanReviewRepository,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GovernanceService:
    def __init__(
        self,
        policy: GovernancePolicyConfig | None = None,
        audit_repository: AuditRepository | None = None,
        human_review_repository: HumanReviewRepository | None = None,
        additional_checks: Sequence[GovernanceCheck] = (),
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._policy = policy or GovernancePolicyConfig()
        self._audit = audit_repository or InMemoryAuditRepository()
        self._human_reviews = (
            human_review_repository or InMemoryHumanReviewRepository()
        )
        self._engine = GovernancePolicyEngine(additional_checks)
        self._clock = clock
        self._id_factory = id_factory

    def review(self, request: GovernanceRequest) -> GovernanceResult:
        evaluation_id = request.evaluation.evaluation_id
        human_review = self._human_reviews.latest(request.candidate_id, evaluation_id)
        result = self._engine.evaluate(
            GovernanceContext(
                request=request,
                policy=self._policy,
                human_review=human_review,
            )
        )
        history = self._audit.list_for_candidate(request.candidate_id)
        self._audit.append(
            GovernanceAuditEvent(
                event_id=self._id_factory(),
                event_type="system_policy_decision",
                candidate_id=request.candidate_id,
                evaluation_id=evaluation_id,
                decision=result.decision,
                reason=result.reason,
                actor=request.requested_by,
                timestamp=self._clock(),
                policy_checks=tuple(result.policy_checks),
                previous_decision=history[-1].decision if history else None,
            )
        )
        return result

    def record_human_decision(
        self, review_input: HumanReviewInput
    ) -> HumanReviewDecision:
        decision = HumanReviewDecision(
            candidate_id=review_input.candidate_id,
            evaluation_id=review_input.evaluation_id,
            decision=review_input.decision,
            reviewer=review_input.reviewer,
            reason=review_input.reason,
            recorded_at=self._clock(),
        )
        history = self._audit.list_for_candidate(review_input.candidate_id)
        self._human_reviews.append(decision)
        self._audit.append(
            GovernanceAuditEvent(
                event_id=self._id_factory(),
                event_type="human_review_decision",
                candidate_id=decision.candidate_id,
                evaluation_id=decision.evaluation_id,
                decision=decision.decision,
                reason=decision.reason or "Explicit human decision recorded.",
                actor=decision.reviewer,
                human_reviewer=decision.reviewer,
                timestamp=decision.recorded_at,
                previous_decision=history[-1].decision if history else None,
            )
        )
        return decision

    def audit_history(self, candidate_id: str) -> tuple[GovernanceAuditEvent, ...]:
        return self._audit.list_for_candidate(candidate_id)

    def human_review_history(
        self, candidate_id: str
    ) -> tuple[HumanReviewDecision, ...]:
        return self._human_reviews.list_for_candidate(candidate_id)
