from __future__ import annotations

from .domain import EvolutionEvent, EvolutionRun, RunState


class InvalidStateTransition(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.RECEIVED: frozenset({RunState.DIAGNOSING, RunState.ABORTED}),
    RunState.DIAGNOSING: frozenset(
        {
            RunState.PROPOSED,
            RunState.NO_ACTION,
            RunState.NEEDS_MORE_EVIDENCE,
            RunState.FAILED,
            RunState.ABORTED,
        }
    ),
    RunState.PROPOSED: frozenset({RunState.RESOLVING, RunState.REJECTED}),
    RunState.RESOLVING: frozenset(
        {RunState.BUILDING, RunState.ABORTED, RunState.FAILED}
    ),
    RunState.BUILDING: frozenset(
        {RunState.VALIDATING, RunState.REVISING, RunState.FAILED, RunState.ABORTED}
    ),
    RunState.VALIDATING: frozenset(
        {RunState.REVISING, RunState.FROZEN, RunState.REJECTED, RunState.FAILED}
    ),
    RunState.REVISING: frozenset(
        {RunState.BUILDING, RunState.REJECTED, RunState.FAILED, RunState.ABORTED}
    ),
    RunState.FROZEN: frozenset({RunState.HOLDOUT, RunState.REJECTED}),
    RunState.HOLDOUT: frozenset(
        {RunState.AWAITING_APPROVAL, RunState.REJECTED, RunState.FAILED}
    ),
    RunState.AWAITING_APPROVAL: frozenset(
        {RunState.ACTIVE, RunState.REJECTED, RunState.ABORTED}
    ),
    RunState.ACTIVE: frozenset(),
    RunState.REJECTED: frozenset(),
    RunState.ABORTED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.NO_ACTION: frozenset(),
    RunState.NEEDS_MORE_EVIDENCE: frozenset(),
}


class EvolutionStateMachine:
    """The sole authority for deterministic EvolutionRun state changes."""

    def transition(
        self,
        run: EvolutionRun,
        next_state: RunState,
        reason: str,
        **details: object,
    ) -> None:
        previous = run.current_state
        if next_state not in _ALLOWED_TRANSITIONS[previous]:
            raise InvalidStateTransition(
                f"Invalid EvolutionRun transition: {previous.value} -> {next_state.value}"
            )
        run.current_state = next_state
        run.history.append(
            EvolutionEvent(previous, next_state, reason, details=details)
        )
