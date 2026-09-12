from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from .errors import DatasetAccessError, HoldoutAccessError
from .models import (
    DatasetPhase,
    DatasetRef,
    DatasetSnapshot,
    DetectionCase,
    DetectionInput,
    EvaluationDataset,
)


VALIDATION_DATASET_REF = DatasetRef(
    DatasetPhase.VALIDATION,
    "manifest://evaluator/taiwan-marketplace-message-demo/validation-v1",
)
HOLDOUT_DATASET_REF = DatasetRef(
    DatasetPhase.HOLDOUT,
    "manifest://evaluator/taiwan-marketplace-message-demo/holdout-v1",
)

_MANIFEST_ROOT = Path(__file__).resolve().parents[1] / "manifests"
DEFAULT_MANIFEST_PATHS: Mapping[DatasetRef, Path] = MappingProxyType(
    {
        VALIDATION_DATASET_REF: _MANIFEST_ROOT / "validation-v1.json",
        HOLDOUT_DATASET_REF: _MANIFEST_ROOT / "holdout-v1.json",
    }
)

_ROOT_FIELDS = frozenset({"manifest_version", "dataset", "cases"})
_DATASET_FIELDS = frozenset({"name", "ref"})
_CASE_FIELDS = frozenset(
    {
        "case_id",
        "subject_type",
        "subject_id",
        "simulation_time",
        "scenario_name",
        "is_fraud",
        "label_provenance",
        "split",
    }
)
_SUPPORTED_SUBJECT_TYPES = frozenset(
    {"account", "shop", "product", "order", "transaction", "message"}
)
_SUPPORTED_MANIFEST_PHASES = frozenset(
    {DatasetPhase.VALIDATION, DatasetPhase.HOLDOUT}
)


class DatasetSource(Protocol):
    """Private storage boundary; implementations may contain ground-truth labels."""

    def load(self, dataset_ref: DatasetRef) -> EvaluationDataset: ...


class ManifestDatasetSource:
    """Strict evaluator-private JSON manifests behind an explicit ref allowlist.

    Construction only records paths. Files are opened on ``load`` so merely giving
    a builder this source through ``BuilderDatasetReader`` cannot open holdout data.
    """

    def __init__(
        self,
        manifests: Mapping[DatasetRef, str | Path] = DEFAULT_MANIFEST_PATHS,
    ) -> None:
        self._manifests = {
            dataset_ref: Path(path) for dataset_ref, path in manifests.items()
        }

    def load(self, dataset_ref: DatasetRef) -> EvaluationDataset:
        if dataset_ref.phase not in _SUPPORTED_MANIFEST_PHASES:
            raise DatasetAccessError(
                "Manifest datasets support only validation and holdout splits"
            )
        try:
            path = self._manifests[dataset_ref]
        except KeyError as exc:
            raise DatasetAccessError(
                f"Unknown manifest dataset: {dataset_ref.phase.value}/{dataset_ref.ref}"
            ) from exc

        payload = self._read_manifest(path)
        root = _strict_object(payload, _ROOT_FIELDS, "manifest")
        if type(root["manifest_version"]) is not int or root["manifest_version"] != 1:
            raise DatasetAccessError("manifest_version must be integer 1")

        dataset = _strict_object(root["dataset"], _DATASET_FIELDS, "dataset")
        name = _non_empty_string(dataset["name"], "dataset.name")
        ref = _non_empty_string(dataset["ref"], "dataset.ref")
        if name != dataset_ref.phase.value:
            raise DatasetAccessError(
                f"Manifest split {name!r} does not match requested split "
                f"{dataset_ref.phase.value!r}"
            )
        if ref != dataset_ref.ref:
            raise DatasetAccessError(
                f"Manifest ref {ref!r} does not match requested ref {dataset_ref.ref!r}"
            )

        cases_payload = root["cases"]
        if not isinstance(cases_payload, list) or not cases_payload:
            raise DatasetAccessError("cases must be a non-empty array")

        records: list[DetectionCase] = []
        seen_case_ids: set[str] = set()
        snapshot: DatasetSnapshot | None = None
        for index, value in enumerate(cases_payload):
            context = f"cases[{index}]"
            item = _strict_object(value, _CASE_FIELDS, context)
            case_id = _non_empty_string(item["case_id"], f"{context}.case_id")
            if case_id in seen_case_ids:
                raise DatasetAccessError(f"Duplicate case_id in manifest: {case_id}")
            seen_case_ids.add(case_id)

            subject_type = _non_empty_string(
                item["subject_type"], f"{context}.subject_type"
            )
            if subject_type not in _SUPPORTED_SUBJECT_TYPES:
                raise DatasetAccessError(
                    f"{context}.subject_type is not supported: {subject_type!r}"
                )
            subject_id = _non_empty_string(
                item["subject_id"], f"{context}.subject_id"
            )
            scenario_name = _non_empty_string(
                item["scenario_name"], f"{context}.scenario_name"
            )
            simulation_time = _aware_datetime(
                item["simulation_time"], f"{context}.simulation_time"
            )
            case_snapshot = DatasetSnapshot(scenario_name, simulation_time)
            if snapshot is None:
                snapshot = case_snapshot
            elif case_snapshot != snapshot:
                raise DatasetAccessError(
                    "All cases in a manifest must use the same scenario_name and "
                    "simulation_time"
                )

            split = _non_empty_string(item["split"], f"{context}.split")
            if split != dataset_ref.phase.value:
                raise DatasetAccessError(
                    f"{context}.split {split!r} does not match requested split "
                    f"{dataset_ref.phase.value!r}"
                )
            if type(item["is_fraud"]) is not bool:
                raise DatasetAccessError(f"{context}.is_fraud must be a boolean")
            provenance = _non_empty_string(
                item["label_provenance"], f"{context}.label_provenance"
            )

            # Environment-backed runners resolve all observable facts by subject.
            # Manifest labels and their provenance stay only on the private case.
            case_input = DetectionInput(
                case_id=case_id,
                subject_type=subject_type,
                subject_id=subject_id,
                facts={},
            )
            records.append(
                DetectionCase(
                    input=case_input,
                    is_fraud=item["is_fraud"],
                    label_provenance=provenance,
                )
            )

        return EvaluationDataset(dataset_ref, tuple(records), snapshot=snapshot)

    @staticmethod
    def _read_manifest(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DatasetAccessError(f"Cannot load manifest {path.name!r}: {exc}") from exc


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


def _strict_object(
    value: Any, expected_fields: frozenset[str], context: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DatasetAccessError(f"{context} must be an object")
    actual_fields = set(value)
    missing = expected_fields - actual_fields
    if missing:
        raise DatasetAccessError(
            f"{context} is missing required fields: {sorted(missing)}"
        )
    unknown = actual_fields - expected_fields
    if unknown:
        raise DatasetAccessError(f"{context} has unknown fields: {sorted(unknown)}")
    return value


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetAccessError(f"{field_name} must be a non-empty string")
    return value


def _aware_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise DatasetAccessError(f"{field_name} must be a date-time string")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DatasetAccessError(f"{field_name} must be a valid date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DatasetAccessError(f"{field_name} must include a timezone offset")
    return parsed
