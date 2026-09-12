from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .adapters import SharedContractAdapter
from .capabilities import BuilderRouter, CapabilityResolver
from .domain import (
    CapabilityKind,
    DiagnosisOutcome,
    EvolutionExecution,
    EvolutionRun,
    RunState,
)
from .ports import CandidateVersionFactory, EvolutionPlanner
from .state_machine import EvolutionStateMachine
from .versioning import VersionManager


IdFactory = Callable[[str], str]
TimestampFactory = Callable[[], str]


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _default_timestamp_factory() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvolutionOrchestrator:
    """Deterministically control one primary policy change per EvolutionRun."""

    def __init__(
        self,
        planner: EvolutionPlanner,
        capability_resolver: CapabilityResolver,
        builder_router: BuilderRouter,
        version_manager: VersionManager,
        candidate_version_factory: CandidateVersionFactory,
        *,
        adapter: SharedContractAdapter | None = None,
        state_machine: EvolutionStateMachine | None = None,
        id_factory: IdFactory = _default_id_factory,
        timestamp_factory: TimestampFactory = _default_timestamp_factory,
    ) -> None:
        self._planner = planner
        self._resolver = capability_resolver
        self._builders = builder_router
        self._versions = version_manager
        self._candidate_versions = candidate_version_factory
        self._adapter = adapter or SharedContractAdapter()
        self._states = state_machine or EvolutionStateMachine()
        self._id_factory = id_factory
        self._timestamp_factory = timestamp_factory

    def execute(
        self, request: Mapping[str, Any], *, retry_budget: int = 0
    ) -> EvolutionExecution:
        context = self._adapter.evolution_context(request)
        run = EvolutionRun(
            run_id=self._id_factory("run"),
            trigger_source=context.trigger_type.value,
            retry_budget=retry_budget,
        )
        self._states.transition(run, RunState.DIAGNOSING, "Starting diagnosis")
        diagnosis = self._planner.diagnose(context)

        if diagnosis.outcome is DiagnosisOutcome.NO_ACTION:
            self._states.transition(run, RunState.NO_ACTION, diagnosis.reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                evolution_result=self._adapter.evolution_result(context, diagnosis),
            )

        if diagnosis.outcome is DiagnosisOutcome.NEEDS_MORE_EVIDENCE:
            self._states.transition(
                run, RunState.NEEDS_MORE_EVIDENCE, diagnosis.reason
            )
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                evolution_result=self._adapter.evolution_result(context, diagnosis),
            )

        gap = diagnosis.primary_gap
        if gap is None:  # guarded by DiagnosisResult, retained as a boundary assertion
            raise ValueError("CHANGE_NEEDED diagnosis has no primary PolicyGap")

        # The external BuildRequest requires PatternSpec even though EvolutionRequest does not.
        if context.pattern_spec is None:
            reason = "A candidate build requires PatternSpec under the shared contract"
            self._states.transition(run, RunState.NEEDS_MORE_EVIDENCE, reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                evolution_result=self._adapter.evolution_result(
                    context, diagnosis, reason_override=reason
                ),
            )

        proposal = self._planner.propose(run, context, diagnosis)
        if proposal.target_policy is not gap.policy_type:
            raise ValueError("Planner proposal must target the selected primary PolicyGap")
        run.target_policy = proposal.target_policy
        run.proposal_ref = proposal.proposal_id
        self._states.transition(
            run,
            RunState.PROPOSED,
            "One primary policy proposal selected",
            considered_policies=[item.value for item in diagnosis.considered_policies],
            unselected_gap_count=max(0, len(diagnosis.policy_gaps) - 1),
        )

        self._states.transition(run, RunState.RESOLVING, "Resolving capability")
        directive = self._resolver.resolve(proposal)
        evolution_result = self._adapter.evolution_result(
            context, diagnosis, proposal
        )
        if directive.kind is CapabilityKind.UNSUPPORTED:
            self._states.transition(run, RunState.ABORTED, directive.reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                proposal=proposal,
                directive=directive,
                evolution_result=evolution_result,
            )

        self._states.transition(
            run,
            RunState.BUILDING,
            f"Routing {directive.kind.value} directive to builder",
        )
        build_id = self._id_factory("build")
        build_request = self._adapter.build_request(build_id, context, proposal)
        builder = self._builders.builder_for(directive)
        build = builder.build(build_request, proposal, directive)
        candidate_result = dict(build.candidate_result)
        base = self._versions.read_base(context.current_defense_version)
        self._versions.register_build(
            candidate_result,
            proposal.target_policy,
            base,
            build.candidate_policy,
        )

        if not build.success:
            self._states.transition(
                run, RunState.FAILED, build.error or "Candidate build failed"
            )
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                proposal=proposal,
                directive=directive,
                evolution_result=evolution_result,
                candidate_result=candidate_result,
            )

        candidate_id = str(candidate_result["candidate_id"])
        run.current_candidate_ref = candidate_id
        self._states.transition(
            run, RunState.VALIDATING, "Candidate built; validation is next"
        )
        candidate_policy = self._versions.candidate_registry.resolve(candidate_id)
        candidate_version = self._candidate_versions.create(
            run, base, candidate_policy, candidate_id
        )
        snapshot = self._versions.compose_candidate(
            base,
            candidate_policy,
            candidate_id,
            candidate_version,
            self._timestamp_factory(),
        )

        return EvolutionExecution(
            run=run,
            diagnosis=diagnosis,
            proposal=proposal,
            directive=directive,
            evolution_result=evolution_result,
            candidate_result=candidate_result,
            candidate_defense_version=self._adapter.defense_version(snapshot),
        )
