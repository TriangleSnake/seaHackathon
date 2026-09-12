"""Append-only in-memory repositories and replaceable storage protocols."""

from __future__ import annotations

from threading import Lock
from typing import Protocol

from .domain.models import GovernanceAuditEvent, HumanReviewDecision


class AuditRepository(Protocol):
    def append(self, event: GovernanceAuditEvent) -> None: ...

    def list_for_candidate(self, candidate_id: str) -> tuple[GovernanceAuditEvent, ...]: ...


class HumanReviewRepository(Protocol):
    def append(self, decision: HumanReviewDecision) -> None: ...

    def latest(
        self, candidate_id: str, evaluation_id: str
    ) -> HumanReviewDecision | None: ...

    def list_for_candidate(self, candidate_id: str) -> tuple[HumanReviewDecision, ...]: ...


class InMemoryAuditRepository:
    """Process-local skeleton with append-only public behavior."""

    def __init__(self) -> None:
        self._events: list[GovernanceAuditEvent] = []
        self._lock = Lock()

    def append(self, event: GovernanceAuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def list_for_candidate(self, candidate_id: str) -> tuple[GovernanceAuditEvent, ...]:
        with self._lock:
            return tuple(
                event for event in self._events if event.candidate_id == candidate_id
            )


class InMemoryHumanReviewRepository:
    """Retains all human actions; a newer decision never overwrites history."""

    def __init__(self) -> None:
        self._decisions: list[HumanReviewDecision] = []
        self._lock = Lock()

    def append(self, decision: HumanReviewDecision) -> None:
        with self._lock:
            self._decisions.append(decision)

    def latest(
        self, candidate_id: str, evaluation_id: str
    ) -> HumanReviewDecision | None:
        with self._lock:
            matches = (
                decision
                for decision in reversed(self._decisions)
                if decision.candidate_id == candidate_id
                and decision.evaluation_id == evaluation_id
            )
            return next(matches, None)

    def list_for_candidate(self, candidate_id: str) -> tuple[HumanReviewDecision, ...]:
        with self._lock:
            return tuple(
                decision
                for decision in self._decisions
                if decision.candidate_id == candidate_id
            )
