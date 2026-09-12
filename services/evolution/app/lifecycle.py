from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .domain import DefenseVersionSnapshot, EvolutionRun, RunState
from .repositories import VersionRepositoryError
from .state_machine import EvolutionStateMachine
from .versioning import VersionManager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VersionLifecycle:
    """Coordinate post-build state without moving governance ownership here."""

    def __init__(
        self,
        versions: VersionManager,
        *,
        state_machine: EvolutionStateMachine | None = None,
        timestamp_factory: Callable[[], str] = _utc_now,
    ) -> None:
        self._versions = versions
        self._states = state_machine or EvolutionStateMachine()
        self._timestamp_factory = timestamp_factory

    def freeze_after_validation(self, run: EvolutionRun) -> None:
        self._states.transition(
            run,
            RunState.FROZEN,
            "Candidate validation passed; snapshot frozen for holdout",
        )

    def begin_holdout(self, run: EvolutionRun) -> None:
        self._states.transition(
            run,
            RunState.HOLDOUT,
            "Beginning evaluator-owned holdout gate",
        )

    def record_evaluation(
        self,
        run: EvolutionRun,
        candidate_version: str,
        evaluation: Mapping[str, Any],
    ) -> DefenseVersionSnapshot:
        if run.current_state not in {RunState.VALIDATING, RunState.HOLDOUT}:
            raise VersionRepositoryError(
                "Evaluation can only be linked during validation or holdout"
            )
        evaluation_state = run.current_state
        failed_iteration = run.iteration
        updated = self._versions.record_evaluation(candidate_version, evaluation)
        run.record_evaluation(
            str(evaluation["candidate_id"]),
            str(evaluation["evaluation_id"]),
            str(evaluation["status"]),
            phase=(
                "validation"
                if evaluation_state is RunState.VALIDATING
                else "holdout"
            ),
        )
        if evaluation.get("status") == "failed":
            if evaluation_state is RunState.VALIDATING and run.retry_budget > 0:
                next_iteration = failed_iteration + 1
                remaining_retries = run.retry_budget - 1
                self._states.transition(
                    run,
                    RunState.REVISING,
                    "Validation failed; retrying with structured feedback",
                    candidate_id=evaluation.get("candidate_id"),
                    evaluation_id=evaluation.get("evaluation_id"),
                    failed_iteration=failed_iteration,
                    next_iteration=next_iteration,
                    retry_budget_remaining=remaining_retries,
                )
                run.iteration = next_iteration
                run.retry_budget = remaining_retries
            else:
                self._states.transition(
                    run,
                    RunState.REJECTED,
                    (
                        "Validation failed and retry budget is exhausted"
                        if evaluation_state is RunState.VALIDATING
                        else "Holdout evaluation failed; candidate rejected"
                    ),
                    candidate_id=evaluation.get("candidate_id"),
                    evaluation_id=evaluation.get("evaluation_id"),
                    failed_iteration=failed_iteration,
                    retry_budget_remaining=run.retry_budget,
                )
        elif evaluation_state is RunState.VALIDATING:
            self.freeze_after_validation(run)
        else:
            self._states.transition(
                run,
                RunState.AWAITING_APPROVAL,
                "Holdout evaluation passed; governance decision required",
                evaluation_id=evaluation.get("evaluation_id"),
            )
        return updated

    def apply_governance(
        self,
        run: EvolutionRun,
        candidate_version: str,
        evaluation: Mapping[str, Any],
        governance_result: object,
    ) -> DefenseVersionSnapshot | None:
        if run.current_state is not RunState.AWAITING_APPROVAL:
            raise VersionRepositoryError("Governance requires an awaiting-approval run")
        decision = _decision_value(governance_result)
        result = self._versions.apply_governance(
            candidate_version,
            evaluation,
            decision,
            self._timestamp_factory(),
        )
        if decision == "needs_review":
            return None
        if decision == "reject":
            self._states.transition(
                run, RunState.REJECTED, "Governance rejected the candidate"
            )
            return result

        if result is None:  # guarded by VersionManager decision handling
            raise VersionRepositoryError("Approval did not create a formal defense")
        self._states.transition(
            run,
            RunState.APPROVED,
            "Governance authorized policy and defense promotion",
            defense_version=result.version,
        )
        return result

    def activate(
        self, run: EvolutionRun, formal_defense_version: str
    ) -> DefenseVersionSnapshot:
        self._states.transition(
            run,
            RunState.ACTIVATING,
            "Activating approved defense in the version repository",
            defense_version=formal_defense_version,
        )
        try:
            activated = self._versions.activate(formal_defense_version)
        except Exception as exc:
            self._states.transition(
                run,
                RunState.FAILED,
                "Defense activation failed; current active defense was preserved",
                error=str(exc),
            )
            raise
        self._states.transition(
            run,
            RunState.ACTIVE,
            "Approved defense activated",
            defense_version=activated.version,
        )
        return activated


def _decision_value(governance_result: object) -> str:
    if isinstance(governance_result, Mapping):
        value = governance_result.get("decision")
    else:
        value = getattr(governance_result, "decision", None)
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str):
        raise VersionRepositoryError("Governance result has no valid decision")
    return value
