from __future__ import annotations

from typing import Protocol

from .errors import DatasetAccessError, HoldoutAccessError
from .models import (
    DatasetPhase,
    DatasetRef,
    DetectionCase,
    DetectionInput,
    EvaluationDataset,
)


class DatasetSource(Protocol):
    """Private storage boundary; implementations may contain ground-truth labels."""

    def load(self, dataset_ref: DatasetRef) -> EvaluationDataset: ...


class EvaluationDatasetReader:
    """Capability used only by evaluators, including final holdout evaluation."""

    def __init__(self, source: DatasetSource) -> None:
        self._source = source

    def load(self, dataset_ref: DatasetRef) -> EvaluationDataset:
        dataset = self._source.load(dataset_ref)
        if dataset.ref != dataset_ref:
            raise DatasetAccessError(
                f"Dataset source returned {dataset.ref!r} for requested {dataset_ref!r}"
            )
        return dataset


class BuilderDatasetReader:
    """Label-stripping development capability that never opens holdout data.

    Builders can receive this narrow capability instead of EvaluationDatasetReader.
    The phase check happens before the underlying source is called, so a holdout's
    labels are not loaded and then merely hidden.
    """

    def __init__(self, source: DatasetSource) -> None:
        self._source = source

    def load_detection_inputs(self, dataset_ref: DatasetRef) -> tuple[DetectionInput, ...]:
        if dataset_ref.phase is DatasetPhase.HOLDOUT:
            raise HoldoutAccessError("Holdout datasets are evaluator-only")

        dataset = self._source.load(dataset_ref)
        if dataset.ref != dataset_ref:
            raise DatasetAccessError(
                f"Dataset source returned {dataset.ref!r} for requested {dataset_ref!r}"
            )

        inputs: list[DetectionInput] = []
        for record in dataset.records:
            if not isinstance(record, DetectionCase):
                raise DatasetAccessError("Dataset contains a non-detection record")
            inputs.append(record.input)
        return tuple(inputs)
