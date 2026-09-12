from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationCommand:
    """One authoritative command run by the outer builder, never by the model."""

    name: str
    argv: tuple[str, ...]
    cwd: str = "{workspace}"
    environment: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    name: str
    argv: tuple[str, ...]
    exit_code: int | None
    status: str
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class CodexExecution:
    executable: str
    version: str | None
    argv: tuple[str, ...]
    exit_code: int | None
    status: str
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class CodeCandidateMetadata:
    build_id: str
    candidate_id: str
    base_commit: str
    candidate_workspace: str | None
    allowed_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]
    path_boundary_valid: bool
    protected_tests_unchanged: bool
    diff_summary: str
    codex: CodexExecution
    tests: tuple[ValidationResult, ...]
    test_status: str
    candidate_commit: str | None
    status: str
    failure_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeBuildResult:
    success: bool
    metadata: CodeCandidateMetadata
    metadata_path: str
