from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_ROOT))

from app.datasets import (
    HOLDOUT_DATASET_REF,
    VALIDATION_DATASET_REF,
    BuilderDatasetReader,
    EvaluationDatasetReader,
    ManifestDatasetSource,
)
from app.errors import DatasetAccessError, HoldoutAccessError
from app.models import DatasetPhase, DatasetRef


MANIFEST_ROOT = EVALUATOR_ROOT / "manifests"
EXPECTED_PROVENANCE = "synthetic-scenario/manual-adjudication"
EXPECTED_TIME = datetime.fromisoformat("2026-09-10T12:00:00+08:00")

VALIDATION_FRAUD = {"MSG-0901", "MSG-0907", "MSG-0911"}
VALIDATION_CLEAN = {"MSG-0002", "MSG-0902", "MSG-0908", "MSG-0912"}
HOLDOUT_FRAUD = {"MSG-0903", "MSG-0909", "MSG-0916"}
HOLDOUT_CLEAN = {"MSG-0009", "MSG-0904", "MSG-0906", "MSG-0910"}


class ManifestDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = ManifestDatasetSource()
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self._file_counter = 0

    def test_validation_manifest_loads_with_private_labels_and_snapshot(self) -> None:
        dataset = EvaluationDatasetReader(self.source).load(VALIDATION_DATASET_REF)

        self.assertEqual(dataset.ref, VALIDATION_DATASET_REF)
        self.assertEqual(len(dataset.records), 7)
        self.assertEqual(
            {record.input.subject_id for record in dataset.records if record.is_fraud},
            VALIDATION_FRAUD,
        )
        self.assertEqual(
            {
                record.input.subject_id
                for record in dataset.records
                if record.is_fraud is False
            },
            VALIDATION_CLEAN,
        )
        self.assertIsNotNone(dataset.snapshot)
        assert dataset.snapshot is not None
        self.assertEqual(dataset.snapshot.scenario_name, "taiwan-marketplace-20260912")
        self.assertEqual(dataset.snapshot.simulation_time, EXPECTED_TIME)
        self.assertTrue(
            all(
                record.label_provenance == EXPECTED_PROVENANCE
                for record in dataset.records
            )
        )

    def test_holdout_manifest_loads_with_both_label_classes(self) -> None:
        dataset = EvaluationDatasetReader(self.source).load(HOLDOUT_DATASET_REF)

        self.assertEqual(dataset.ref, HOLDOUT_DATASET_REF)
        self.assertEqual(len(dataset.records), 7)
        self.assertEqual(
            {record.input.subject_id for record in dataset.records if record.is_fraud},
            HOLDOUT_FRAUD,
        )
        self.assertEqual(
            {
                record.input.subject_id
                for record in dataset.records
                if record.is_fraud is False
            },
            HOLDOUT_CLEAN,
        )
        self.assertEqual(dataset.snapshot.simulation_time, EXPECTED_TIME)

    def test_only_the_scoped_environment_message_ids_are_represented(self) -> None:
        validation = self.source.load(VALIDATION_DATASET_REF)
        holdout = self.source.load(HOLDOUT_DATASET_REF)

        actual_ids = {
            record.input.subject_id
            for dataset in (validation, holdout)
            for record in dataset.records
        }
        self.assertEqual(
            actual_ids,
            VALIDATION_FRAUD
            | VALIDATION_CLEAN
            | HOLDOUT_FRAUD
            | HOLDOUT_CLEAN,
        )
        self.assertTrue(
            all(
                record.input.subject_type == "message"
                for dataset in (validation, holdout)
                for record in dataset.records
            )
        )

    def test_builder_inputs_contain_no_labels_or_label_metadata(self) -> None:
        inputs = BuilderDatasetReader(self.source).load_detection_inputs(
            VALIDATION_DATASET_REF
        )

        self.assertEqual(len(inputs), 7)
        for case_input in inputs:
            self.assertEqual(dict(case_input.facts), {})
            self.assertFalse(hasattr(case_input, "is_fraud"))
            self.assertFalse(hasattr(case_input, "label_provenance"))
            self.assertNotIn("is_fraud", vars(case_input))
            self.assertNotIn("label_provenance", vars(case_input))

    def test_builder_rejects_holdout_without_opening_its_manifest(self) -> None:
        missing_path = Path(self._temporary_directory.name) / "must-not-open.json"
        source = ManifestDatasetSource({HOLDOUT_DATASET_REF: missing_path})

        with self.assertRaisesRegex(HoldoutAccessError, "evaluator-only"):
            BuilderDatasetReader(source).load_detection_inputs(HOLDOUT_DATASET_REF)

    def test_malformed_json_is_rejected(self) -> None:
        source = self._source_for_text("{not-json")

        with self.assertRaisesRegex(DatasetAccessError, "Cannot load manifest"):
            source.load(VALIDATION_DATASET_REF)

    def test_duplicate_case_ids_are_rejected(self) -> None:
        payload = self._validation_payload()
        payload["cases"].append(copy.deepcopy(payload["cases"][0]))

        with self.assertRaisesRegex(DatasetAccessError, "Duplicate case_id"):
            self._source_for_payload(payload).load(VALIDATION_DATASET_REF)

    def test_missing_and_unknown_fields_are_rejected(self) -> None:
        missing = self._validation_payload()
        del missing["cases"][0]["subject_id"]
        with self.assertRaisesRegex(DatasetAccessError, "missing required fields"):
            self._source_for_payload(missing).load(VALIDATION_DATASET_REF)

        unknown = self._validation_payload()
        unknown["cases"][0]["expected_detection"] = True
        with self.assertRaisesRegex(DatasetAccessError, "unknown fields"):
            self._source_for_payload(unknown).load(VALIDATION_DATASET_REF)

    def test_invalid_field_types_times_and_subjects_are_rejected(self) -> None:
        invalid_cases = (
            ("is_fraud", 1, "is_fraud must be a boolean"),
            ("simulation_time", "2026-09-10T12:00:00", "timezone offset"),
            ("simulation_time", "not-a-time", "valid date-time"),
            ("subject_type", "unsupported", "subject_type is not supported"),
        )
        for field, value, message in invalid_cases:
            with self.subTest(field=field, value=value):
                payload = self._validation_payload()
                payload["cases"][0][field] = value
                with self.assertRaisesRegex(DatasetAccessError, message):
                    self._source_for_payload(payload).load(VALIDATION_DATASET_REF)

    def test_manifest_ref_and_case_split_must_match_requested_ref(self) -> None:
        wrong_ref = self._validation_payload()
        wrong_ref["dataset"]["ref"] = HOLDOUT_DATASET_REF.ref
        with self.assertRaisesRegex(DatasetAccessError, "does not match requested ref"):
            self._source_for_payload(wrong_ref).load(VALIDATION_DATASET_REF)

        wrong_split = self._validation_payload()
        wrong_split["cases"][0]["split"] = "holdout"
        with self.assertRaisesRegex(DatasetAccessError, "does not match requested split"):
            self._source_for_payload(wrong_split).load(VALIDATION_DATASET_REF)

    def test_unknown_refs_and_build_manifests_are_rejected(self) -> None:
        unknown = DatasetRef(DatasetPhase.VALIDATION, "manifest://unknown")
        with self.assertRaisesRegex(DatasetAccessError, "Unknown manifest dataset"):
            self.source.load(unknown)

        build = DatasetRef(DatasetPhase.BUILD, "manifest://build")
        with self.assertRaisesRegex(DatasetAccessError, "only validation and holdout"):
            ManifestDatasetSource({build: MANIFEST_ROOT / "validation-v1.json"}).load(
                build
            )

    def _validation_payload(self) -> dict[str, object]:
        return json.loads(
            (MANIFEST_ROOT / "validation-v1.json").read_text(encoding="utf-8")
        )

    def _source_for_payload(self, payload: dict[str, object]) -> ManifestDatasetSource:
        return self._source_for_text(json.dumps(payload, ensure_ascii=False))

    def _source_for_text(self, text: str) -> ManifestDatasetSource:
        self._file_counter += 1
        path = (
            Path(self._temporary_directory.name)
            / f"validation-{self._file_counter}.json"
        )
        path.write_text(text, encoding="utf-8")
        return ManifestDatasetSource({VALIDATION_DATASET_REF: path})


if __name__ == "__main__":
    unittest.main()
