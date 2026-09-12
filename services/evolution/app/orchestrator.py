from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .adapters import SharedContractAdapter
from .capabilities import BuilderRouter, CapabilityResolver
from .domain import (
    CapabilityKind,
    ConfigListOperation,
    DETECTION_CHAT_REQUEST_PHRASES_PATH,
    DetectionPolicyChange,
    DiagnosisOutcome,
    DiagnosisResult,
    EvolutionContext,
    EvolutionExecution,
    EvolutionRun,
    PolicyChangeProposal,
    RevisionFeedback,
    RunState,
)
from .lifecycle import VersionLifecycle
from .ports import CandidateVersionFactory, EvolutionPlanner
from .repositories import VersionRepositoryError
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
        self._lifecycle = VersionLifecycle(
            version_manager,
            state_machine=self._states,
            timestamp_factory=timestamp_factory,
        )
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
        try:
            diagnosis = self._planner.diagnose(context)
            if not isinstance(diagnosis, DiagnosisResult):
                raise TypeError("Planner diagnose() must return DiagnosisResult")
        except Exception as exc:
            self._states.transition(
                run,
                RunState.FAILED,
                "Planner diagnosis failed",
                error=str(exc),
            )
            raise

        if diagnosis.outcome is DiagnosisOutcome.NO_ACTION:
            self._states.transition(run, RunState.NO_ACTION, diagnosis.reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                evolution_result=self._adapter.evolution_result(context, diagnosis),
                context=context,
            )

        if diagnosis.outcome is DiagnosisOutcome.NEEDS_MORE_EVIDENCE:
            self._states.transition(
                run, RunState.NEEDS_MORE_EVIDENCE, diagnosis.reason
            )
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                evolution_result=self._adapter.evolution_result(context, diagnosis),
                context=context,
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
                context=context,
            )

        try:
            proposal = self._planner.propose(run, context, diagnosis)
            if not isinstance(proposal, PolicyChangeProposal):
                raise TypeError("Planner propose() must return PolicyChangeProposal")
            self._validate_proposal(proposal, context, diagnosis)
            run.record_proposal(proposal)
        except Exception as exc:
            self._states.transition(
                run,
                RunState.FAILED,
                "Planner failed to create a valid initial proposal",
                error=str(exc),
            )
            raise
        self._states.transition(
            run,
            RunState.PROPOSED,
            "One primary policy proposal selected",
            proposal_id=proposal.proposal_id,
            iteration=run.iteration,
            considered_policies=[item.value for item in diagnosis.considered_policies],
            unselected_gap_count=max(0, len(diagnosis.policy_gaps) - 1),
        )

        evolution_result = self._adapter.evolution_result(
            context, diagnosis, proposal
        )
        return self._resolve_and_build(
            run,
            context,
            diagnosis,
            proposal,
            evolution_result,
            feedback=None,
        )

    def handle_evaluation(
        self,
        execution: EvolutionExecution,
        evaluation: Mapping[str, Any],
    ) -> EvolutionExecution:
        """Link one evaluation and autonomously build the next revision if allowed."""

        run = execution.run
        if run.current_state not in {RunState.VALIDATING, RunState.HOLDOUT}:
            raise VersionRepositoryError(
                "Evaluation can only be handled during validation or holdout"
            )
        if execution.proposal is None or execution.context is None:
            raise ValueError("A built EvolutionExecution requires proposal and context")
        candidate_version = _candidate_version(execution)
        failed_iteration = run.iteration
        feedback: RevisionFeedback | None = None
        if (
            run.current_state is RunState.VALIDATING
            and evaluation.get("status") == "failed"
            and run.retry_budget > 0
        ):
            feedback = self._adapter.revision_feedback(
                evaluation,
                execution.proposal,
                iteration=failed_iteration,
            )

        updated = self._lifecycle.record_evaluation(
            run, candidate_version, evaluation
        )
        if run.current_state is not RunState.REVISING:
            return replace(
                execution,
                candidate_defense_version=self._adapter.defense_version(updated),
            )
        if feedback is None:  # guarded by the lifecycle retry decision
            raise ValueError("A revising run requires structured evaluation feedback")
        return self.revise(execution, feedback)

    def revise(
        self,
        execution: EvolutionExecution,
        feedback: RevisionFeedback,
    ) -> EvolutionExecution:
        """Create and build a new proposal for a run already in REVISING."""

        run = execution.run
        if run.current_state is not RunState.REVISING:
            raise VersionRepositoryError("A revised proposal requires a REVISING run")
        if execution.context is None or execution.proposal is None:
            raise ValueError("Revision requires the previous proposal and run context")
        if feedback.previous_proposal != execution.proposal:
            raise ValueError("RevisionFeedback does not reference the previous proposal")
        if not isinstance(execution.candidate_result, Mapping):
            raise ValueError("Revision requires the failed CandidateResult")
        if feedback.candidate_id != execution.candidate_result.get("candidate_id"):
            raise ValueError("RevisionFeedback does not reference the failed candidate")

        try:
            proposal = self._planner.propose(
                run,
                execution.context,
                execution.diagnosis,
                feedback=feedback,
            )
            if not isinstance(proposal, PolicyChangeProposal):
                raise TypeError("Planner propose() must return PolicyChangeProposal")
            self._validate_proposal(
                proposal, execution.context, execution.diagnosis
            )
            run.record_proposal(proposal)
        except Exception as exc:
            self._states.transition(
                run,
                RunState.FAILED,
                "Planner failed to create a valid revised proposal",
                error=str(exc),
                failed_candidate_id=feedback.candidate_id,
                failed_evaluation_id=feedback.evaluation_id,
            )
            raise

        evolution_result = self._adapter.evolution_result(
            execution.context, execution.diagnosis, proposal
        )
        return self._resolve_and_build(
            run,
            execution.context,
            execution.diagnosis,
            proposal,
            evolution_result,
            feedback=feedback,
        )

    def _resolve_and_build(
        self,
        run: EvolutionRun,
        context: EvolutionContext,
        diagnosis: DiagnosisResult,
        proposal: PolicyChangeProposal,
        evolution_result: Mapping[str, Any],
        *,
        feedback: RevisionFeedback | None,
    ) -> EvolutionExecution:
        self._states.transition(
            run,
            RunState.RESOLVING,
            "Resolving capability for policy proposal",
            proposal_id=proposal.proposal_id,
            iteration=run.iteration,
        )
        try:
            base = self._versions.read_base(context.current_defense_version)
        except LookupError:
            reason = (
                "Base defense version is unavailable: "
                f"{context.current_defense_version}"
            )
            self._states.transition(run, RunState.ABORTED, reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                proposal=proposal,
                evolution_result=evolution_result,
                context=context,
                revision_feedback=feedback,
            )

        matching_base_policies = tuple(
            policy
            for policy in base.policies
            if policy.policy_type is proposal.target_policy
        )
        if len(matching_base_policies) != 1:
            reason = "Base defense must contain exactly one target policy reference"
            self._states.transition(run, RunState.ABORTED, reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                proposal=proposal,
                evolution_result=evolution_result,
                context=context,
                revision_feedback=feedback,
            )
        if (
            proposal.base_policy_version is not None
            and proposal.base_policy_version != matching_base_policies[0].version
        ):
            reason = (
                "Proposed base policy artifact does not match the base defense "
                f"reference: {proposal.base_policy_version} != "
                f"{matching_base_policies[0].version}"
            )
            self._states.transition(run, RunState.ABORTED, reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                proposal=proposal,
                evolution_result=evolution_result,
                context=context,
                revision_feedback=feedback,
            )

        proposal = self._bind_detection_config(
            proposal, matching_base_policies[0].version
        )
        # The planner creates behavioral intent. Persist the runtime-enriched,
        # typed CONFIG proposal in the same immutable attempt lineage.
        current_attempt = run.attempts[-1]
        run.attempts[-1] = replace(current_attempt, proposal=proposal)

        directive = self._resolver.resolve(proposal)
        if directive.kind is CapabilityKind.UNSUPPORTED:
            self._states.transition(run, RunState.ABORTED, directive.reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                proposal=proposal,
                directive=directive,
                evolution_result=evolution_result,
                context=context,
                revision_feedback=feedback,
            )

        build_id = self._id_factory("build")
        if self._versions.candidate_registry.has_build(build_id):
            reason = f"Build id is already registered: {build_id}"
            self._states.transition(run, RunState.FAILED, reason)
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                proposal=proposal,
                directive=directive,
                evolution_result=evolution_result,
                context=context,
                revision_feedback=feedback,
            )
        self._states.transition(
            run,
            RunState.BUILDING,
            f"Routing {directive.kind.value} directive to builder",
            proposal_id=proposal.proposal_id,
            iteration=run.iteration,
        )
        build_request = self._adapter.build_request(build_id, context, proposal)
        builder = self._builders.builder_for(directive)
        build = builder.build(build_request, proposal, directive)
        candidate_result = dict(build.candidate_result)
        self._versions.register_build(
            candidate_result,
            proposal.target_policy,
            base,
            build.candidate_policy,
        )
        candidate_id = str(candidate_result["candidate_id"])

        if not build.success:
            run.record_candidate(candidate_id, None)
            self._states.transition(
                run,
                RunState.FAILED,
                build.error or "Candidate build failed",
                proposal_id=proposal.proposal_id,
                candidate_id=candidate_id,
                iteration=run.iteration,
            )
            return EvolutionExecution(
                run=run,
                diagnosis=diagnosis,
                proposal=proposal,
                directive=directive,
                evolution_result=evolution_result,
                candidate_result=candidate_result,
                context=context,
                revision_feedback=feedback,
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
        run.record_candidate(candidate_id, candidate_version)
        self._states.transition(
            run,
            RunState.VALIDATING,
            "Candidate built; validation is next",
            proposal_id=proposal.proposal_id,
            candidate_id=candidate_id,
            candidate_version=candidate_version,
            iteration=run.iteration,
        )

        return EvolutionExecution(
            run=run,
            diagnosis=diagnosis,
            proposal=proposal,
            directive=directive,
            evolution_result=evolution_result,
            candidate_result=candidate_result,
            candidate_defense_version=self._adapter.defense_version(snapshot),
            context=context,
            revision_feedback=feedback,
        )

    @staticmethod
    def _validate_proposal(
        proposal: PolicyChangeProposal,
        context: EvolutionContext,
        diagnosis: DiagnosisResult,
    ) -> None:
        gap = diagnosis.primary_gap
        if gap is None or proposal.target_policy is not gap.policy_type:
            raise ValueError(
                "Planner proposal must target the selected primary PolicyGap"
            )
        if proposal.base_defense_version != context.current_defense_version:
            raise ValueError("Planner proposal must retain the run's base defense")

    @staticmethod
    def _bind_detection_config(
        proposal: PolicyChangeProposal, base_policy_version: str
    ) -> PolicyChangeProposal:
        """Bind planner intent to H's typed CONFIG contract deterministically."""

        if proposal.base_policy_version not in {None, base_policy_version}:
            return proposal
        if proposal.detection_policy_changes or proposal.mutation_intent is None:
            return replace(proposal, base_policy_version=base_policy_version)

        intent = proposal.mutation_intent
        operation = {
            "append_unique": ConfigListOperation.ADD,
            "remove": ConfigListOperation.REMOVE,
        }.get(intent.operation)
        if (
            intent.path != DETECTION_CHAT_REQUEST_PHRASES_PATH
            or operation is None
            or any(not isinstance(value, str) for value in intent.values)
        ):
            return replace(proposal, base_policy_version=base_policy_version)
        change = DetectionPolicyChange(
            path=intent.path,
            operation=operation,
            values=tuple(intent.values),
        )
        return replace(
            proposal,
            base_policy_version=base_policy_version,
            detection_policy_changes=(change,),
        )


def _candidate_version(execution: EvolutionExecution) -> str:
    candidate = execution.candidate_defense_version
    if not isinstance(candidate, Mapping):
        raise ValueError("EvolutionExecution has no candidate defense version")
    version = candidate.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("Candidate defense version is invalid")
    return version
