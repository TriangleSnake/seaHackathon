from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.artifacts import ArtifactConflictError, FileArtifactPublisher


class FileArtifactPublisherTests(unittest.TestCase):
    def test_publish_uses_version_filename_and_deterministic_utf8_json(self) -> None:
        artifact = {
            "version": "DP-CAND-001",
            "rule_based": {"chat_request_phrases": ["付款"]},
            "default_checks": ["rule_based", "anomaly"],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "candidate-policies"
            publisher = FileArtifactPublisher(root)

            reference = publisher.publish("DP-CAND-001", artifact)

            target = root / "DP-CAND-001.json"
            expected = (
                json.dumps(
                    artifact,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
            self.assertEqual(publisher.root, root)
            self.assertEqual(reference, str(target))
            self.assertEqual(target.read_bytes(), expected)
            self.assertIn("付款".encode("utf-8"), target.read_bytes())

    def test_publish_rejects_filename_and_internal_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "candidate-policies"
            publisher = FileArtifactPublisher(root)

            with self.assertRaisesRegex(ValueError, "must match"):
                publisher.publish("DP-CAND-001", {"version": "DP-CAND-002"})

            self.assertFalse(root.exists())

    def test_identical_republish_is_idempotent_and_cleans_temporary_file(self) -> None:
        artifact = {"version": "DP-CAND-001", "enabled": True}
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            publisher = FileArtifactPublisher(root)

            first_reference = publisher.publish("DP-CAND-001", artifact)
            second_reference = publisher.publish("DP-CAND-001", artifact)

            self.assertEqual(second_reference, first_reference)
            self.assertEqual(
                [path.name for path in root.iterdir()], ["DP-CAND-001.json"]
            )

    def test_conflict_preserves_existing_artifact(self) -> None:
        original = {"version": "DP-CAND-001", "phrases": ["付款"]}
        conflicting = {"version": "DP-CAND-001", "phrases": ["轉帳"]}
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            publisher = FileArtifactPublisher(root)
            target = Path(publisher.publish("DP-CAND-001", original))
            original_bytes = target.read_bytes()

            with self.assertRaises(ArtifactConflictError):
                publisher.publish("DP-CAND-001", conflicting)

            self.assertEqual(target.read_bytes(), original_bytes)
            self.assertEqual(
                [path.name for path in root.iterdir()], ["DP-CAND-001.json"]
            )

    def test_unsafe_versions_are_rejected_before_creating_root(self) -> None:
        unsafe_versions = (
            "",
            "../DP-CAND-001",
            "nested/DP-CAND-001",
            "-DP-CAND-001",
            "DP CAND 001",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "candidate-policies"
            publisher = FileArtifactPublisher(root)

            for version in unsafe_versions:
                with self.subTest(version=version):
                    with self.assertRaisesRegex(ValueError, "Unsafe"):
                        publisher.publish(version, {"version": version})

            self.assertFalse(root.exists())

    def test_existing_symlink_is_rejected_even_when_target_content_matches(
        self,
    ) -> None:
        artifact = {"version": "DP-CAND-001", "phrases": ["付款"]}
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "candidate-policies"
            root.mkdir()
            outside = Path(temporary_directory) / "outside.json"
            outside.write_text(
                json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (root / "DP-CAND-001.json").symlink_to(outside)

            with self.assertRaises(ArtifactConflictError):
                FileArtifactPublisher(root).publish("DP-CAND-001", artifact)

            self.assertTrue((root / "DP-CAND-001.json").is_symlink())
            self.assertEqual(json.loads(outside.read_text(encoding="utf-8")), artifact)


if __name__ == "__main__":
    unittest.main()
