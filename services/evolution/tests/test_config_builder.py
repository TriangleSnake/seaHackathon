from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from app.capabilities import (
    BuilderRouter,
    CapabilityResolver,
    DetectionPolicyCapabilityAdapter,
)
from app.config_builder import ConfigBuildError, ConfigBuilder, ConfigBuilderSettings
from app.domain import (
    ArtifactBoundary,
    CapabilityKind,
    ConfigListOperation,
    DETECTION_CHAT_REQUEST_PHRASES_PATH,
    DefenseVersionSnapshot,
    DetectionPolicyChange,
    DiagnosisOutcome,
    DiagnosisResult,
    EvolutionContext,
    EvolutionRun,
    GapSeverity,
    ImplementationDirective,
    PolicyChangeProposal,
    PolicyGap,
    PolicyReference,
    PolicyType,
    RunState,
)
from app.orchestrator import EvolutionOrchestrator
from app.repositories import InMemoryCandidatePolicyRegistry, InMemoryVersionRepository
from app.versioning import VersionManager


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BASELINE_DIR = REPOSITORY_ROOT / "services" / "detection" / "config" / "policies"
BASELINE_PATH = BASELINE_DIR / "baseline-v1.json"
SCHEMA_PATH = REPOSITORY_ROOT / "shared" / "schemas" / "detection-policy.schema.json"
SCHEMA_ROOT = REPOSITORY_ROOT / "shared" / "schemas"


def change(
    operation: ConfigListOperation,
    *values: str,
    path: str = DETECTION_CHAT_REQUEST_PHRASES_PATH,
) -> DetectionPolicyChange:
    return DetectionPolicyChange(path=path, operation=operation, values=values)


def proposal(
    *changes: DetectionPolicyChange,
    base_policy_version: str = "baseline-v1",
    base_defense_version: str = "DV-001",
) -> PolicyChangeProposal:
    return PolicyChangeProposal(
        proposal_id="proposal-config",
        target_policy=PolicyType.DETECTION,
        base_defense_version=base_defense_version,
        objective="Improve suspicious chat coverage",
        requested_behavior="Apply approved phrase-list mutations",
        provenance={"source": "test"},
        base_policy_version=base_policy_version,
        detection_policy_changes=changes,
    )


def build_request(
    build_id: str = "build-config", base_defense_version: str = "DV-001"
) -> dict:
    return {
        "build_id": build_id,
        "pattern_spec": {"pattern_id": "pattern-config"},
        "base_defense_version": {"version": base_defense_version},
        "target_policies": ["detection"],
    }


class ConfigBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.candidate_dir = Path(self.temporary_directory.name) / "candidate-policies"
        self.registry = InMemoryCandidatePolicyRegistry()
        self.settings = ConfigBuilderSettings(
            baseline_policy_dir=BASELINE_DIR,
            candidate_policy_dir=self.candidate_dir,
            detection_policy_schema=SCHEMA_PATH,
        )
        self.builder = ConfigBuilder.from_settings(self.settings, self.registry)

    def test_clone_baseline_changes_only_candidate_version_and_not_source_file(
        self,
    ) -> None:
        before_bytes = BASELINE_PATH.read_bytes()
        baseline = json.loads(before_bytes)
        candidate_proposal = proposal()
        directive = ImplementationDirective(
            directive_id="directive-clone",
            kind=CapabilityKind.CONFIG,
            target_policy=PolicyType.DETECTION,
            summary="Clone for validation",
            boundary=ArtifactBoundary(allowed_paths=("candidate/detection/",)),
            base_policy_version="baseline-v1",
        )

        outcome = self.builder.build(build_request(), candidate_proposal, directive)

        self.assertTrue(outcome.success, outcome.error)
        assert outcome.candidate_policy is not None
        self.assertEqual(outcome.candidate_policy.policy_ref.version, "DP-CAND-001")
        candidate = json.loads(
            Path(outcome.candidate_policy.artifact_ref or "").read_text(
                encoding="utf-8"
            )
        )
        expected = deepcopy(baseline)
        expected["version"] = "DP-CAND-001"
        self.assertEqual(candidate, expected)
        self.assertEqual(BASELINE_PATH.read_bytes(), before_bytes)

    def test_add_phrase_publishes_runtime_and_schema_valid_candidate_result(
        self,
    ) -> None:
        candidate_proposal = proposal(change(ConfigListOperation.ADD, "付款"))
        directive = DetectionPolicyCapabilityAdapter().resolve(candidate_proposal)

        outcome = self.builder.build(build_request(), candidate_proposal, directive)

        self.assertTrue(outcome.success, outcome.error)
        assert outcome.candidate_policy is not None
        version = outcome.candidate_policy.policy_ref.version
        artifact = self.candidate_dir / f"{version}.json"
        self.assertEqual(artifact, Path(outcome.candidate_policy.artifact_ref or ""))
        self.assertEqual(artifact.name, "DP-CAND-001.json")
        document = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(document["version"], "DP-CAND-001")
        self.assertEqual(document["rule_based"]["chat_request_phrases"][-1], "付款")
        Draft202012Validator(
            json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        ).validate(document)
        self.assertEqual(outcome.candidate_result["status"], "built")
        self.assertEqual(
            outcome.candidate_result["changes"][0]["artifact_path"], str(artifact)
        )
        _validate_candidate_result(outcome.candidate_result)

        _, repository_type = _load_detection_components()
        loaded = repository_type(self.candidate_dir).resolve(version)
        self.assertEqual(loaded.version, "DP-CAND-001")
        self.assertEqual(loaded.rule_based.chat_request_phrases[-1], "付款")

    def test_second_candidate_can_remove_broad_phrase_and_add_refinement(self) -> None:
        first_proposal = proposal(change(ConfigListOperation.ADD, "付款"))
        first = self.builder.build(
            build_request("build-first"),
            first_proposal,
            DetectionPolicyCapabilityAdapter().resolve(first_proposal),
        )
        self.assertTrue(first.success, first.error)

        second_proposal = proposal(
            change(ConfigListOperation.REMOVE, "付款"),
            change(ConfigListOperation.ADD, "請透過平台付款"),
            base_policy_version="DP-CAND-001",
            base_defense_version="DV-CAND-001",
        )
        second = self.builder.build(
            build_request("build-second", "DV-CAND-001"),
            second_proposal,
            DetectionPolicyCapabilityAdapter().resolve(second_proposal),
        )

        self.assertTrue(second.success, second.error)
        assert second.candidate_policy is not None
        self.assertEqual(second.candidate_policy.policy_ref.version, "DP-CAND-002")
        document = json.loads(
            Path(second.candidate_policy.artifact_ref or "").read_text(encoding="utf-8")
        )
        phrases = document["rule_based"]["chat_request_phrases"]
        self.assertNotIn("付款", phrases)
        self.assertEqual(phrases[-1], "請透過平台付款")

    def test_unsupported_config_field_is_rejected_without_publication(self) -> None:
        unsupported = change(
            ConfigListOperation.ADD, "5", path="anomaly.messages_per_hour"
        )
        candidate_proposal = proposal(unsupported)
        forced_config = ImplementationDirective(
            directive_id="directive-forced",
            kind=CapabilityKind.CONFIG,
            target_policy=PolicyType.DETECTION,
            summary="Invalid forced config",
            base_policy_version="baseline-v1",
            detection_policy_changes=(unsupported,),
        )

        outcome = self.builder.build(build_request(), candidate_proposal, forced_config)

        self.assertFalse(outcome.success)
        self.assertEqual(outcome.candidate_result["status"], "failed")
        self.assertIn("Unsupported Detection CONFIG field", outcome.error or "")
        self.assertFalse(self.candidate_dir.exists())

    def test_existing_version_with_different_content_fails_without_overwrite(
        self,
    ) -> None:
        first_proposal = proposal(change(ConfigListOperation.ADD, "付款"))
        first = self.builder.build(
            build_request("build-first"),
            first_proposal,
            DetectionPolicyCapabilityAdapter().resolve(first_proposal),
        )
        self.assertTrue(first.success, first.error)
        original_path = self.candidate_dir / "DP-CAND-001.json"
        original_bytes = original_path.read_bytes()

        fresh_registry = InMemoryCandidatePolicyRegistry()
        restarted_builder = ConfigBuilder.from_settings(self.settings, fresh_registry)
        conflicting_proposal = proposal(change(ConfigListOperation.ADD, "轉帳"))
        conflict = restarted_builder.build(
            build_request("build-conflict"),
            conflicting_proposal,
            DetectionPolicyCapabilityAdapter().resolve(conflicting_proposal),
        )

        self.assertFalse(conflict.success)
        self.assertIn("different content", conflict.error or "")
        self.assertEqual(original_path.read_bytes(), original_bytes)

    def test_invalid_baseline_is_rejected_by_runtime_validation(self) -> None:
        invalid_root = Path(self.temporary_directory.name) / "invalid-baseline"
        invalid_root.mkdir()
        (invalid_root / "bad-v1.json").write_text(
            json.dumps({"version": "bad-v1"}), encoding="utf-8"
        )
        invalid_builder = ConfigBuilder.from_settings(
            ConfigBuilderSettings(
                baseline_policy_dir=invalid_root,
                candidate_policy_dir=self.candidate_dir,
                detection_policy_schema=SCHEMA_PATH,
            ),
            self.registry,
        )
        candidate_proposal = proposal(
            change(ConfigListOperation.ADD, "付款"), base_policy_version="bad-v1"
        )

        outcome = invalid_builder.build(
            build_request(),
            candidate_proposal,
            DetectionPolicyCapabilityAdapter().resolve(candidate_proposal),
        )

        self.assertFalse(outcome.success)
        self.assertIn("validation error", (outcome.error or "").lower())
        self.assertFalse(self.candidate_dir.exists())

    def test_schema_validates_uncoerced_baseline_document(self) -> None:
        invalid_root = Path(self.temporary_directory.name) / "coercible-baseline"
        invalid_root.mkdir()
        document = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        document["version"] = "coercible-v1"
        document["rule_based"]["access_window_minutes"] = "120"
        (invalid_root / "coercible-v1.json").write_text(
            json.dumps(document), encoding="utf-8"
        )
        invalid_builder = ConfigBuilder.from_settings(
            ConfigBuilderSettings(
                baseline_policy_dir=invalid_root,
                candidate_policy_dir=self.candidate_dir,
                detection_policy_schema=SCHEMA_PATH,
            ),
            self.registry,
        )
        candidate_proposal = proposal(
            change(ConfigListOperation.ADD, "付款"),
            base_policy_version="coercible-v1",
        )

        outcome = invalid_builder.build(
            build_request(),
            candidate_proposal,
            DetectionPolicyCapabilityAdapter().resolve(candidate_proposal),
        )

        self.assertFalse(outcome.success)
        self.assertIn("shared schema", outcome.error or "")
        self.assertFalse(self.candidate_dir.exists())

    def test_real_builder_is_registered_once_by_existing_orchestrator(self) -> None:
        candidate_proposal = proposal(change(ConfigListOperation.ADD, "付款"))
        base = _base_defense()
        version_repository = InMemoryVersionRepository([base])
        manager = VersionManager(version_repository, self.registry)
        orchestrator = EvolutionOrchestrator(
            planner=_Planner(candidate_proposal),
            capability_resolver=CapabilityResolver(
                {PolicyType.DETECTION: DetectionPolicyCapabilityAdapter()}
            ),
            builder_router=BuilderRouter({CapabilityKind.CONFIG: self.builder}),
            version_manager=manager,
            candidate_version_factory=_CandidateDefenseVersionFactory(),
            id_factory=lambda prefix: f"{prefix}-config",
            timestamp_factory=lambda: "2026-09-12T02:00:00+00:00",
        )

        execution = orchestrator.execute(_evolution_request())

        result = execution.candidate_result
        self.assertIsNotNone(result)
        assert result is not None
        record = self.registry.get(result["candidate_id"])
        self.assertEqual(record.candidate_policy_version, "DP-CAND-001")
        self.assertEqual(record.artifact_ref, result["changes"][0]["artifact_path"])
        self.assertEqual(len(self.registry.list_records()), 1)
        self.assertEqual(
            execution.candidate_defense_version["policies"][0],
            {"type": "detection", "version": "DP-CAND-001"},
        )

    def test_base_policy_lineage_mismatch_aborts_before_publication(self) -> None:
        candidate_proposal = proposal(change(ConfigListOperation.ADD, "付款"))
        mismatched_base = DefenseVersionSnapshot(
            version="DV-001",
            status="active",
            policies=(PolicyReference(PolicyType.DETECTION, "DP-001"),),
            created_at="2026-09-12T00:00:00+00:00",
        )
        manager = VersionManager(
            InMemoryVersionRepository([mismatched_base]), self.registry
        )
        orchestrator = EvolutionOrchestrator(
            planner=_Planner(candidate_proposal),
            capability_resolver=CapabilityResolver(
                {PolicyType.DETECTION: DetectionPolicyCapabilityAdapter()}
            ),
            builder_router=BuilderRouter({CapabilityKind.CONFIG: self.builder}),
            version_manager=manager,
            candidate_version_factory=_CandidateDefenseVersionFactory(),
            id_factory=lambda prefix: f"{prefix}-lineage",
        )

        execution = orchestrator.execute(_evolution_request())

        self.assertIs(execution.run.current_state, RunState.ABORTED)
        self.assertIsNone(execution.candidate_result)
        self.assertFalse(self.candidate_dir.exists())
        self.assertEqual(self.registry.list_records(), ())
        self.assertIn(
            "does not match",
            execution.run.history[-1].reason,
        )

    def test_duplicate_build_id_is_rejected_without_orphan_artifact(self) -> None:
        candidate_proposal = proposal(change(ConfigListOperation.ADD, "付款"))
        manager = VersionManager(
            InMemoryVersionRepository([_base_defense()]), self.registry
        )
        orchestrator = EvolutionOrchestrator(
            planner=_Planner(candidate_proposal),
            capability_resolver=CapabilityResolver(
                {PolicyType.DETECTION: DetectionPolicyCapabilityAdapter()}
            ),
            builder_router=BuilderRouter({CapabilityKind.CONFIG: self.builder}),
            version_manager=manager,
            candidate_version_factory=_CandidateDefenseVersionFactory(),
            id_factory=lambda prefix: f"{prefix}-duplicate",
        )
        first = orchestrator.execute(_evolution_request())
        first_bytes = (self.candidate_dir / "DP-CAND-001.json").read_bytes()

        second = orchestrator.execute(_evolution_request())

        self.assertIsNotNone(first.candidate_result)
        self.assertIs(second.run.current_state, RunState.FAILED)
        self.assertIsNone(second.candidate_result)
        self.assertIn("already registered", second.run.history[-1].reason)
        self.assertEqual(
            [path.name for path in self.candidate_dir.iterdir()],
            ["DP-CAND-001.json"],
        )
        self.assertEqual(
            (self.candidate_dir / "DP-CAND-001.json").read_bytes(), first_bytes
        )

    def test_unknown_base_defense_aborts_before_publication(self) -> None:
        candidate_proposal = proposal(
            change(ConfigListOperation.ADD, "付款"),
            base_defense_version="DV-404",
        )
        manager = VersionManager(
            InMemoryVersionRepository([_base_defense()]), self.registry
        )
        orchestrator = EvolutionOrchestrator(
            planner=_Planner(candidate_proposal),
            capability_resolver=CapabilityResolver(
                {PolicyType.DETECTION: DetectionPolicyCapabilityAdapter()}
            ),
            builder_router=BuilderRouter({CapabilityKind.CONFIG: self.builder}),
            version_manager=manager,
            candidate_version_factory=_CandidateDefenseVersionFactory(),
            id_factory=lambda prefix: f"{prefix}-missing-base",
        )
        request = _evolution_request()
        request["current_defense_version"] = {"version": "DV-404"}

        execution = orchestrator.execute(request)

        self.assertIs(execution.run.current_state, RunState.ABORTED)
        self.assertIsNone(execution.candidate_result)
        self.assertFalse(self.candidate_dir.exists())
        self.assertIn("unavailable", execution.run.history[-1].reason)

    def test_candidate_directory_is_required_and_environment_configurable(self) -> None:
        with self.assertRaisesRegex(ConfigBuildError, "DETECTION_CANDIDATE_POLICY_DIR"):
            ConfigBuilderSettings.from_env({}, repository_root=REPOSITORY_ROOT)
        with self.assertRaisesRegex(ConfigBuildError, "DETECTION_CANDIDATE_POLICY_DIR"):
            ConfigBuilderSettings.from_env(
                {"DETECTION_CANDIDATE_POLICY_DIR": "   "},
                repository_root=REPOSITORY_ROOT,
            )

        configured = ConfigBuilderSettings.from_env(
            {"DETECTION_CANDIDATE_POLICY_DIR": str(self.candidate_dir)},
            repository_root=REPOSITORY_ROOT,
        )
        self.assertEqual(configured.candidate_policy_dir, self.candidate_dir)
        self.assertEqual(configured.baseline_policy_dir, BASELINE_DIR)
        self.assertEqual(configured.detection_policy_schema, SCHEMA_PATH)


class _Planner:
    def __init__(self, candidate_proposal: PolicyChangeProposal) -> None:
        self._proposal = candidate_proposal

    def diagnose(self, context: EvolutionContext) -> DiagnosisResult:
        del context
        return DiagnosisResult(
            outcome=DiagnosisOutcome.CHANGE_NEEDED,
            reason="Fixture change",
            policy_gaps=(
                PolicyGap(
                    policy_type=PolicyType.DETECTION,
                    severity=GapSeverity.HIGH,
                    confidence=1.0,
                    symptom="Missed suspicious phrase",
                    hypothesized_cause="Phrase absent from policy",
                ),
            ),
            considered_policies=(PolicyType.DETECTION,),
            primary_gap_index=0,
        )

    def propose(
        self,
        run: EvolutionRun,
        context: EvolutionContext,
        diagnosis: DiagnosisResult,
    ) -> PolicyChangeProposal:
        del run, context, diagnosis
        return self._proposal


class _CandidateDefenseVersionFactory:
    def create(
        self,
        run: EvolutionRun,
        base: DefenseVersionSnapshot,
        candidate_policy,
        candidate_id: str,
    ) -> str:
        del run, base, candidate_policy, candidate_id
        return "DV-CAND-001"


def _base_defense() -> DefenseVersionSnapshot:
    return DefenseVersionSnapshot(
        version="DV-001",
        status="active",
        policies=(
            PolicyReference(PolicyType.DETECTION, "baseline-v1"),
            PolicyReference(PolicyType.SCORING, "SP-001"),
            PolicyReference(PolicyType.EXPLORATION, "EP-001"),
            PolicyReference(PolicyType.INVESTIGATION, "IP-001"),
            PolicyReference(PolicyType.ASSOCIATION, "AP-001"),
        ),
        created_at="2026-09-12T00:00:00+00:00",
    )


def _evolution_request() -> dict:
    return {
        "trigger": {"type": "new_spec_ready", "context": {"source": "test"}},
        "current_defense_version": {"version": "DV-001"},
        "system_performance": {"recall": 0.5},
        "pattern_spec": {
            "pattern_id": "pattern-config",
            "name": "Config pattern",
            "description": "Fixture",
            "observed_signals": [],
            "current_defense_gap": "Missing phrase",
            "confidence": 1.0,
            "evidence_refs": [],
        },
    }


def _validate_candidate_result(payload: dict) -> None:
    registry = Registry()
    for schema_path in SCHEMA_ROOT.glob("*.schema.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "candidate.schema.json#/$defs/CandidateResult",
        },
        registry=registry,
    ).validate(payload)


def _load_detection_components():
    from app.config_builder import _import_detection_policy_components

    return _import_detection_policy_components()


if __name__ == "__main__":
    unittest.main()
