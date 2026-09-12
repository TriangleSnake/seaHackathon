from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .contracts import parse_evaluation_request, render_evaluation_result
from .datasets import EvaluationDatasetReader
from .errors import DatasetAccessError, EvaluationPlanError, SnapshotGuardError
from .models import DatasetSnapshot, EvaluationDataset, EvaluationJob, EvaluationPlan
from .router import EvaluatorRouter
from .snapshots import EnvironmentSnapshotGuard


class EvaluationPlanResolver(Protocol):
    """Trusted registry boundary missing from the current shared request schema."""

    def resolve(self, candidate_id: str, baseline_defense_version: str) -> EvaluationPlan: ...


class EvaluationService:
    """Shared-contract entry point; returns metrics but never dataset rows or labels."""

    def __init__(
        self,
        router: EvaluatorRouter,
        plan_resolver: EvaluationPlanResolver,
        datasets: EvaluationDatasetReader,
        snapshot_guard: EnvironmentSnapshotGuard | None = None,
    ) -> None:
        self._router = router
        self._plan_resolver = plan_resolver
        self._datasets = datasets
        self._snapshot_guard = snapshot_guard

    def evaluate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = parse_evaluation_request(payload)
        plan = self._plan_resolver.resolve(
            request.candidate_id, request.baseline_defense_version
        )
        if plan.baseline_defense_version != request.baseline_defense_version:
            raise EvaluationPlanError(
                "Resolved plan does not match requested baseline defense version"
            )

        phases = {dataset_ref.phase for dataset_ref in request.datasets}
        if len(phases) != 1:
            raise DatasetAccessError(
                "Build, validation, and holdout phases must be evaluated separately"
            )
        loaded_datasets = tuple(
            self._datasets.load(dataset_ref) for dataset_ref in request.datasets
        )

        expected_snapshot = self._expected_snapshot(loaded_datasets)
        if expected_snapshot is not None and self._snapshot_guard is None:
            raise SnapshotGuardError(
                "Snapshot-backed evaluation requires an Environment snapshot guard"
            )
        if self._snapshot_guard is not None and expected_snapshot is None:
            raise SnapshotGuardError(
                "Every dataset must provide snapshot metadata when a snapshot guard "
                "is configured"
            )

        # request.requested_thresholds is intentionally not included in the job.
        # Gate configuration is injected into each evaluator through a trusted
        # provider, so a candidate cannot alter the rules used against itself.
        job = EvaluationJob(
            evaluation_id=request.evaluation_id,
            candidate_id=request.candidate_id,
            plan=plan,
            datasets=loaded_datasets,
        )
        evaluator = self._router.get(plan.policy_type)
        if self._snapshot_guard is None:
            outcome = evaluator.evaluate(job)
        else:
            before = self._snapshot_guard.capture(expected_snapshot)
            try:
                outcome = evaluator.evaluate(job)
            finally:
                self._snapshot_guard.verify_unchanged(before)
        return render_evaluation_result(request, outcome)

    @staticmethod
    def _expected_snapshot(
        datasets: tuple[EvaluationDataset, ...],
    ) -> DatasetSnapshot | None:
        snapshots = tuple(dataset.snapshot for dataset in datasets)
        if not any(snapshot is not None for snapshot in snapshots):
            return None
        if any(snapshot is None for snapshot in snapshots):
            raise SnapshotGuardError(
                "All datasets in one evaluation must provide snapshot metadata"
            )

        expected = snapshots[0]
        if any(snapshot != expected for snapshot in snapshots[1:]):
            raise SnapshotGuardError(
                "All datasets in one evaluation must use the same Environment snapshot"
            )
        return expected
