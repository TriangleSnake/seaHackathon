"""Small, extensible set of deterministic governance checks."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import (
    CheckOutcome,
    GovernanceContext,
    GovernanceDecision,
    PolicyCheckResult,
)


class GovernanceCheck(Protocol):
    """Extension point for trusted checks configured outside candidate artifacts."""

    def evaluate(self, context: GovernanceContext) -> CheckOutcome: ...


class EvaluationPassedCheck:
    def evaluate(self, context: GovernanceContext) -> CheckOutcome:
        passed = context.request.evaluation.status == "passed"
        reason = (
            "Evaluation status is passed."
            if passed
            else "Evaluation status is failed; governance approval is prohibited."
        )
        return CheckOutcome(
            result=PolicyCheckResult(
                name="evaluation_passed", passed=passed, reason=reason
            ),
            failure_decision=None if passed else GovernanceDecision.REJECT,
        )


class ImplementationValidCheck:
    def evaluate(self, context: GovernanceContext) -> CheckOutcome:
        passed = context.request.evaluation.implementation_valid
        reason = (
            "Candidate implementation is valid."
            if passed
            else "Candidate implementation is invalid; governance approval is prohibited."
        )
        return CheckOutcome(
            result=PolicyCheckResult(
                name="implementation_valid", passed=passed, reason=reason
            ),
            failure_decision=None if passed else GovernanceDecision.REJECT,
        )


class ReportedRegressionsCheck:
    """Provisional rule: block reported regressions when trusted policy enables it."""

    def evaluate(self, context: GovernanceContext) -> CheckOutcome:
        regressions = context.request.evaluation.regressions
        if not context.policy.block_reported_regressions:
            return CheckOutcome(
                result=PolicyCheckResult(
                    name="no_blocking_regressions",
                    passed=True,
                    reason="Trusted policy does not currently block reported regressions.",
                )
            )

        passed = not regressions
        reason = (
            "No blocking evaluation regressions were reported."
            if passed
            else f"{len(regressions)} blocking evaluation regression(s) were reported."
        )
        return CheckOutcome(
            result=PolicyCheckResult(
                name="no_blocking_regressions", passed=passed, reason=reason
            ),
            failure_decision=None if passed else GovernanceDecision.REJECT,
        )


class HumanApprovalRequirementCheck:
    def evaluate(self, context: GovernanceContext) -> CheckOutcome:
        required = (
            context.policy.require_human_approval
            or context.request.require_human_approval
        )
        if not required:
            return CheckOutcome(
                result=PolicyCheckResult(
                    name="human_approval",
                    passed=True,
                    reason="Human approval is not required by trusted policy or request.",
                )
            )

        review = context.human_review
        if review is None:
            return CheckOutcome(
                result=PolicyCheckResult(
                    name="human_approval",
                    passed=False,
                    reason="Explicit human approval is required and has not been recorded.",
                ),
                failure_decision=GovernanceDecision.NEEDS_REVIEW,
            )

        if review.decision == GovernanceDecision.REJECT:
            return CheckOutcome(
                result=PolicyCheckResult(
                    name="human_approval",
                    passed=False,
                    reason=f"Human reviewer {review.reviewer} explicitly rejected the candidate.",
                ),
                failure_decision=GovernanceDecision.REJECT,
            )

        return CheckOutcome(
            result=PolicyCheckResult(
                name="human_approval",
                passed=True,
                reason=f"Human reviewer {review.reviewer} explicitly approved the candidate.",
            )
        )
