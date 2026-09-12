"""Deterministic governance decision engine."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.checks import (
    EvaluationPassedCheck,
    GovernanceCheck,
    HumanApprovalRequirementCheck,
    ImplementationValidCheck,
    ReportedRegressionsCheck,
)
from app.domain.models import GovernanceContext, GovernanceDecision, GovernanceResult


class GovernancePolicyEngine:
    def __init__(self, additional_checks: Sequence[GovernanceCheck] = ()) -> None:
        self._checks: tuple[GovernanceCheck, ...] = (
            EvaluationPassedCheck(),
            ImplementationValidCheck(),
            ReportedRegressionsCheck(),
            *additional_checks,
            HumanApprovalRequirementCheck(),
        )

    def evaluate(self, context: GovernanceContext) -> GovernanceResult:
        outcomes = tuple(check.evaluate(context) for check in self._checks)
        failed_rejections = [
            outcome
            for outcome in outcomes
            if not outcome.result.passed
            and outcome.failure_decision != GovernanceDecision.NEEDS_REVIEW
        ]
        if failed_rejections:
            reason = "; ".join(
                outcome.result.reason or outcome.result.name
                for outcome in failed_rejections
            )
            decision = GovernanceDecision.REJECT
        elif any(
            not outcome.result.passed
            and outcome.failure_decision == GovernanceDecision.NEEDS_REVIEW
            for outcome in outcomes
        ):
            decision = GovernanceDecision.NEEDS_REVIEW
            reason = "Human approval is required before promotion can be authorized."
        else:
            decision = GovernanceDecision.APPROVE
            reason = (
                "All required governance checks passed; promotion is authorized but not executed."
            )

        return GovernanceResult(
            decision=decision,
            reason=reason,
            policy_checks=[outcome.result for outcome in outcomes],
            approved_defense_version=None,
        )
