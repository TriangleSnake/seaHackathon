from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from .adapters import SharedContractAdapter
from .artifacts import FileArtifactPublisher
from .domain import (
    BuildOutcome,
    CandidatePolicy,
    CapabilityKind,
    ConfigListOperation,
    DETECTION_CHAT_REQUEST_PHRASES_PATH,
    DetectionPolicyChange,
    ImplementationDirective,
    PolicyChangeProposal,
    PolicyReference,
    PolicyType,
)
from .ports import ArtifactPublisher, CandidatePolicyRegistry


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _import_detection_policy_components() -> tuple[type[Any], type[Any]]:
    """Load Detection's own model/repository in either supported test layout."""

    repository_root = str(_REPOSITORY_ROOT)
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)
    from services.detection.app.policies.models import DetectionPolicy
    from services.detection.app.policies.repository import FilePolicyRepository

    return DetectionPolicy, FilePolicyRepository


class DetectionPolicyRepository(Protocol):
    def read_document(self, version: str) -> dict[str, Any]: ...


class ConfigBuildError(ValueError):
    pass


class DetectionPolicyValidationError(ConfigBuildError):
    pass


@dataclass(frozen=True)
class ConfigBuilderSettings:
    baseline_policy_dir: Path
    candidate_policy_dir: Path
    detection_policy_schema: Path

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        repository_root: str | Path = _REPOSITORY_ROOT,
    ) -> "ConfigBuilderSettings":
        values = os.environ if environ is None else environ
        candidate_dir = values.get("DETECTION_CANDIDATE_POLICY_DIR")
        if not candidate_dir or not candidate_dir.strip():
            raise ConfigBuildError(
                "DETECTION_CANDIDATE_POLICY_DIR must configure candidate publication"
            )
        root = Path(repository_root)
        return cls(
            baseline_policy_dir=Path(
                values.get(
                    "DETECTION_BASE_POLICY_DIR",
                    str(root / "services" / "detection" / "config" / "policies"),
                )
            ),
            candidate_policy_dir=Path(candidate_dir),
            detection_policy_schema=Path(
                values.get(
                    "DETECTION_POLICY_SCHEMA_PATH",
                    str(root / "shared" / "schemas" / "detection-policy.schema.json"),
                )
            ),
        )


class DetectionPolicyValidator:
    """Validate with Detection's runtime model and the shared JSON Schema."""

    def __init__(self, runtime_model: type[Any], schema_path: str | Path) -> None:
        self._runtime_model = runtime_model
        self._schema_path = Path(schema_path)
        try:
            schema = json.loads(self._schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DetectionPolicyValidationError(
                f"Unable to load detection policy schema: {self._schema_path}"
            ) from exc
        Draft202012Validator.check_schema(schema)
        self._schema = Draft202012Validator(schema)

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise DetectionPolicyValidationError(
                "Detection policy must be a JSON object"
            )

        source = deepcopy(dict(payload))
        schema_errors = sorted(
            self._schema.iter_errors(source),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        runtime_error: Exception | None = None
        try:
            policy = self._runtime_model.model_validate(source)
            normalized = policy.model_dump(mode="json")
        except Exception as exc:  # Pydantic is owned by Detection, not Evolution.
            runtime_error = exc
            normalized = source
        if runtime_error is not None or schema_errors:
            details: list[str] = []
            if runtime_error is not None:
                details.append(f"runtime model: {runtime_error}")
            if schema_errors:
                first = schema_errors[0]
                location = ".".join(str(part) for part in first.absolute_path)
                prefix = f" at {location}" if location else ""
                details.append(f"shared schema{prefix}: {first.message}")
            raise DetectionPolicyValidationError("; ".join(details))
        return normalized


class ConfigBuilder:
    """Build immutable Detection CONFIG candidates without changing detector code."""

    def __init__(
        self,
        policy_repositories: Sequence[DetectionPolicyRepository],
        validator: DetectionPolicyValidator,
        publisher: ArtifactPublisher,
        candidate_registry: CandidatePolicyRegistry,
        *,
        adapter: SharedContractAdapter | None = None,
    ) -> None:
        if not policy_repositories:
            raise ConfigBuildError(
                "At least one detection policy repository is required"
            )
        self._policy_repositories = tuple(policy_repositories)
        self._validator = validator
        self._publisher = publisher
        self._candidates = candidate_registry
        self._adapter = adapter or SharedContractAdapter()

    @classmethod
    def from_settings(
        cls,
        settings: ConfigBuilderSettings,
        candidate_registry: CandidatePolicyRegistry,
        *,
        adapter: SharedContractAdapter | None = None,
    ) -> "ConfigBuilder":
        runtime_model, repository_type = _import_detection_policy_components()
        repository_dirs = [settings.baseline_policy_dir]
        if settings.candidate_policy_dir != settings.baseline_policy_dir:
            repository_dirs.append(settings.candidate_policy_dir)
        repositories = tuple(repository_type(path) for path in repository_dirs)
        return cls(
            repositories,
            DetectionPolicyValidator(runtime_model, settings.detection_policy_schema),
            FileArtifactPublisher(settings.candidate_policy_dir),
            candidate_registry,
            adapter=adapter,
        )

    @classmethod
    def from_env(
        cls,
        candidate_registry: CandidatePolicyRegistry,
        environ: Mapping[str, str] | None = None,
        *,
        repository_root: str | Path = _REPOSITORY_ROOT,
        adapter: SharedContractAdapter | None = None,
    ) -> "ConfigBuilder":
        return cls.from_settings(
            ConfigBuilderSettings.from_env(environ, repository_root=repository_root),
            candidate_registry,
            adapter=adapter,
        )

    def build(
        self,
        build_request: Mapping[str, Any],
        proposal: PolicyChangeProposal,
        directive: ImplementationDirective,
    ) -> BuildOutcome:
        build_id = _required_string(build_request, "build_id")
        candidate_id = f"candidate-{build_id}"
        try:
            self._validate_request(build_request, proposal, directive)
            base_policy_version = proposal.base_policy_version
            if base_policy_version is None:  # guarded above, keeps type checkers honest
                raise ConfigBuildError(
                    "Detection CONFIG build requires base_policy_version"
                )

            baseline_document = self._validator.validate(
                self._read_policy_document(base_policy_version)
            )
            candidate_document = deepcopy(baseline_document)
            self._apply_changes(candidate_document, directive.detection_policy_changes)

            candidate_version = self._candidates.allocate_candidate_policy_version(
                PolicyType.DETECTION
            )
            candidate_document["version"] = candidate_version
            candidate_document = self._validator.validate(candidate_document)
            artifact_ref = self._publisher.publish(
                candidate_version, candidate_document
            )
            summary = self._change_summary(
                base_policy_version,
                candidate_version,
                directive.detection_policy_changes,
            )
            result = self._adapter.candidate_result(
                candidate_id=candidate_id,
                build_id=build_id,
                base_defense_version=proposal.base_defense_version,
                status="built",
                changes=(
                    {
                        "target": PolicyType.DETECTION.value,
                        "operation": "modify",
                        "artifact_path": artifact_ref,
                        "summary": summary,
                    },
                ),
                artifact_root=str(self._publisher.root),
                build_log_ref=None,
            )
            return BuildOutcome(
                success=True,
                candidate_result=result,
                candidate_policy=CandidatePolicy(
                    target_policy=PolicyType.DETECTION,
                    policy_ref=PolicyReference(PolicyType.DETECTION, candidate_version),
                    artifact_ref=artifact_ref,
                ),
            )
        except Exception as exc:
            result = self._adapter.candidate_result(
                candidate_id=candidate_id,
                build_id=build_id,
                base_defense_version=proposal.base_defense_version,
                status="failed",
                changes=(),
                artifact_root=None,
                build_log_ref=None,
            )
            return BuildOutcome(False, result, error=str(exc))

    def _read_policy_document(self, version: str) -> dict[str, Any]:
        errors: list[Exception] = []
        for repository in self._policy_repositories:
            try:
                return repository.read_document(version)
            except LookupError as exc:
                errors.append(exc)
        raise ConfigBuildError(
            f"Detection base policy artifact not found: {version}"
        ) from (errors[-1] if errors else None)

    @staticmethod
    def _validate_request(
        build_request: Mapping[str, Any],
        proposal: PolicyChangeProposal,
        directive: ImplementationDirective,
    ) -> None:
        if proposal.target_policy is not PolicyType.DETECTION:
            raise ConfigBuildError("ConfigBuilder only supports Detection policies")
        if directive.kind is not CapabilityKind.CONFIG:
            raise ConfigBuildError("ConfigBuilder requires a CONFIG directive")
        if directive.target_policy is not PolicyType.DETECTION:
            raise ConfigBuildError("CONFIG directive must target Detection")
        if not proposal.base_policy_version:
            raise ConfigBuildError(
                "Detection CONFIG build requires base_policy_version"
            )
        if directive.base_policy_version != proposal.base_policy_version:
            raise ConfigBuildError(
                "Directive base policy artifact does not match the approved proposal"
            )
        if directive.detection_policy_changes != proposal.detection_policy_changes:
            raise ConfigBuildError(
                "Directive mutations do not match the approved proposal"
            )
        if list(build_request.get("target_policies", ())) != [
            PolicyType.DETECTION.value
        ]:
            raise ConfigBuildError(
                "Detection CONFIG build must target exactly one detection policy"
            )
        base_ref = build_request.get("base_defense_version")
        if not isinstance(base_ref, Mapping) or base_ref.get("version") != (
            proposal.base_defense_version
        ):
            raise ConfigBuildError(
                "BuildRequest base defense does not match the approved proposal"
            )

    @staticmethod
    def _apply_changes(
        document: dict[str, Any], changes: Sequence[DetectionPolicyChange]
    ) -> None:
        seen: dict[tuple[str, str], ConfigListOperation] = {}
        for change in changes:
            if change.path != DETECTION_CHAT_REQUEST_PHRASES_PATH:
                raise ConfigBuildError(
                    f"Unsupported Detection CONFIG field: {change.path}"
                )
            phrases = document["rule_based"]["chat_request_phrases"]
            if not isinstance(phrases, list):
                raise ConfigBuildError(
                    "Detection policy chat_request_phrases must be a list"
                )
            for value in change.values:
                key = (change.path, value)
                previous = seen.get(key)
                if previous is not None:
                    raise ConfigBuildError(
                        f"Duplicate or conflicting mutation for phrase: {value!r}"
                    )
                seen[key] = change.operation
                if change.operation is ConfigListOperation.ADD:
                    if value in phrases:
                        raise ConfigBuildError(
                            f"Cannot add existing chat request phrase: {value!r}"
                        )
                    phrases.append(value)
                elif change.operation is ConfigListOperation.REMOVE:
                    if value not in phrases:
                        raise ConfigBuildError(
                            f"Cannot remove missing chat request phrase: {value!r}"
                        )
                    phrases.remove(value)
                else:  # DetectionPolicyChange validates this; retain boundary defense.
                    raise ConfigBuildError(
                        f"Unsupported phrase-list operation: {change.operation!r}"
                    )

    @staticmethod
    def _change_summary(
        base_version: str,
        candidate_version: str,
        changes: Sequence[DetectionPolicyChange],
    ) -> str:
        if not changes:
            return (
                f"Cloned Detection policy {base_version} as {candidate_version} "
                "without config value changes"
            )
        operations = ", ".join(
            f"{change.operation.value} {len(change.values)} value(s) at {change.path}"
            for change in changes
        )
        return f"Built {candidate_version} from {base_version}: {operations}"


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigBuildError(f"BuildRequest {key} must be a non-empty string")
    return value
