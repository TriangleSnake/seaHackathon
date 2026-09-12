from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from .models import (
    CodeBuildResult,
    CodeCandidateMetadata,
    CodexExecution,
    ValidationCommand,
    ValidationResult,
)


_DEFAULT_ALLOWED_PATHS = (
    "services/detection/app/repository.py",
    "services/detection/app/detectors/rules.py",
)
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
_OUTPUT_LIMIT = 40_000
_PASSTHROUGH_ENVIRONMENT = {
    "CODEX_HOME",
    "HOME",
    "LANG",
    "LOGNAME",
    "PATH",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TERM",
    "TMPDIR",
    "USER",
}


class CodeBuilderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodeBuilderSettings:
    source_repository: Path
    base_commit: str
    candidate_root: Path
    artifact_root: Path
    protected_test_paths: tuple[Path, ...]
    validation_commands: tuple[ValidationCommand, ...]
    codex_executable: str = "codex"
    allowed_paths: tuple[str, ...] = _DEFAULT_ALLOWED_PATHS
    codex_timeout_seconds: float = 900.0
    validation_timeout_seconds: float = 300.0

    @classmethod
    def for_detection(
        cls,
        *,
        source_repository: str | Path,
        base_commit: str,
        acceptance_test: str | Path,
        candidate_root: str | Path,
        artifact_root: str | Path,
        codex_executable: str = "codex",
    ) -> "CodeBuilderSettings":
        python = sys.executable
        tests = Path(acceptance_test).resolve()
        no_bytecode = (
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("PYTHONPATH", "{workspace}/services/detection"),
            ("DETECTION_CANDIDATE_ROOT", "{workspace}/services/detection"),
        )
        return cls(
            source_repository=Path(source_repository).resolve(),
            base_commit=base_commit,
            candidate_root=Path(candidate_root).resolve(),
            artifact_root=Path(artifact_root).resolve(),
            protected_test_paths=(tests,),
            validation_commands=(
                ValidationCommand(
                    name="authoritative_acceptance",
                    argv=(
                        python,
                        "-m",
                        "pytest",
                        "-p",
                        "no:cacheprovider",
                        "-q",
                        str(tests),
                    ),
                    cwd="{workspace}/services/detection/app",
                    environment=no_bytecode,
                ),
                ValidationCommand(
                    name="detection_regression",
                    argv=(
                        python,
                        "-m",
                        "pytest",
                        "-p",
                        "no:cacheprovider",
                        "-q",
                        "tests",
                    ),
                    cwd="{workspace}/services/detection",
                    environment=(("PYTHONDONTWRITEBYTECODE", "1"),),
                ),
                ValidationCommand(
                    name="detection_compile",
                    argv=(
                        python,
                        "-c",
                        (
                            "from pathlib import Path; "
                            "files=sorted(Path('app').rglob('*.py')); "
                            "[compile(p.read_text(encoding='utf-8'), str(p), 'exec') "
                            "for p in files]; print(f'compiled {len(files)} files')"
                        ),
                    ),
                    cwd="{workspace}/services/detection",
                    environment=(("PYTHONDONTWRITEBYTECODE", "1"),),
                ),
                ValidationCommand(
                    name="git_diff_check",
                    argv=("git", "diff", "--check"),
                    cwd="{workspace}",
                ),
            ),
            codex_executable=codex_executable,
        )


class RealCodexCodeBuilder:
    """Build a code candidate in a detached worktree and fail closed.

    The Codex process receives a writable root at Detection's ``app`` directory.
    Authoritative acceptance tests remain outside the candidate worktree.  Git
    path validation is still mandatory because the app directory contains files
    beyond the two paths approved for this capability.
    """

    def __init__(
        self,
        settings: CodeBuilderSettings,
        *,
        process_environment: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self._environment = dict(os.environ if process_environment is None else process_environment)

    def build(
        self,
        *,
        build_id: str,
        candidate_id: str,
        objective: str,
        requested_behavior: str,
        required_signals: Sequence[str],
        known_risks: Sequence[str],
        allowed_paths: Sequence[str],
    ) -> CodeBuildResult:
        workspace: Path | None = None
        codex = CodexExecution(
            executable=self.settings.codex_executable,
            version=None,
            argv=(),
            exit_code=None,
            status="not_started",
        )
        changed_paths: tuple[str, ...] = ()
        path_valid = False
        protected_unchanged = True
        tests: tuple[ValidationResult, ...] = ()
        test_status = "not_run"
        diff_summary = ""
        candidate_commit: str | None = None
        failure: str | None = None

        try:
            allowed = self._validate_boundary(allowed_paths)
            executable = self._resolve_codex_executable()
            version = self._codex_version(executable)
            self._validate_base_commit()
            protected_before = self._protected_test_digests()
            workspace = self._create_worktree(candidate_id)
            prompt = self._implementation_prompt(
                objective=objective,
                requested_behavior=requested_behavior,
                required_signals=required_signals,
                known_risks=known_risks,
                allowed_paths=allowed,
            )
            codex = self._invoke_codex(executable, version, workspace, prompt)
            protected_unchanged = protected_before == self._protected_test_digests()
            if not protected_unchanged:
                raise CodeBuilderError("A protected authoritative test changed during Codex execution")
            if self._git(workspace, "rev-parse", "HEAD").stdout.strip() != self.settings.base_commit:
                raise CodeBuilderError("Codex changed candidate Git history; only working-tree edits are permitted")

            changed_paths = self._changed_paths(workspace)
            path_valid = set(changed_paths).issubset(set(allowed))
            if not path_valid:
                forbidden = sorted(set(changed_paths) - set(allowed))
                raise CodeBuilderError(f"Codex changed forbidden paths: {forbidden}")
            if codex.status != "succeeded":
                raise CodeBuilderError(
                    "Codex invocation did not succeed"
                    + (f": {codex.stderr.strip()}" if codex.stderr.strip() else "")
                )
            if not changed_paths:
                raise CodeBuilderError("Codex produced no implementation changes")

            patch_before = self._working_patch_digest(workspace)
            tests = self._run_validations(workspace)
            test_status = "passed" if all(item.status == "passed" for item in tests) else "failed"
            if test_status != "passed":
                failed = next(item for item in tests if item.status != "passed")
                raise CodeBuilderError(f"Authoritative validation failed: {failed.name}")
            if patch_before != self._working_patch_digest(workspace):
                raise CodeBuilderError("Validation commands modified the candidate implementation")
            if protected_before != self._protected_test_digests():
                protected_unchanged = False
                raise CodeBuilderError("A protected authoritative test changed during validation")
            if self._changed_paths(workspace) != changed_paths:
                raise CodeBuilderError("Candidate changed after path-boundary validation")

            candidate_commit = self._commit_candidate(workspace, candidate_id, changed_paths)
            diff_summary = self._git(
                workspace,
                "diff",
                "--stat",
                f"{self.settings.base_commit}..{candidate_commit}",
            ).stdout.strip()
        except Exception as exc:
            failure = str(exc)
            if workspace is not None:
                try:
                    changed_paths = self._changed_paths(workspace)
                    path_valid = set(changed_paths).issubset(set(self.settings.allowed_paths))
                    diff_summary = self._git(
                        workspace, "diff", "--stat", self.settings.base_commit
                    ).stdout.strip()
                except Exception:
                    pass

        status = "built" if failure is None else "failed"
        metadata = CodeCandidateMetadata(
            build_id=build_id,
            candidate_id=candidate_id,
            base_commit=self.settings.base_commit,
            candidate_workspace=str(workspace) if workspace else None,
            allowed_paths=tuple(self.settings.allowed_paths),
            changed_paths=changed_paths,
            path_boundary_valid=path_valid,
            protected_tests_unchanged=protected_unchanged,
            diff_summary=diff_summary,
            codex=codex,
            tests=tests,
            test_status=test_status,
            candidate_commit=candidate_commit,
            status=status,
            failure_reason=failure,
        )
        metadata_path = self._publish_metadata(metadata)
        return CodeBuildResult(failure is None, metadata, str(metadata_path))

    def _validate_boundary(self, allowed_paths: Sequence[str]) -> tuple[str, ...]:
        requested = tuple(allowed_paths)
        if requested != self.settings.allowed_paths:
            raise CodeBuilderError(
                "ImplementationDirective write boundary does not match the runtime allow-list"
            )
        if len(requested) != len(set(requested)):
            raise CodeBuilderError("Allowed implementation paths must be unique")
        return requested

    def _resolve_codex_executable(self) -> str:
        configured = self.settings.codex_executable
        resolved = shutil.which(configured) if not Path(configured).is_absolute() else configured
        if not resolved or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
            raise CodeBuilderError(f"Real Codex executable is unavailable: {configured}")
        return str(Path(resolved).resolve())

    def _codex_version(self, executable: str) -> str:
        result = self._run((executable, "--version"), cwd=self.settings.source_repository, timeout=30)
        if result.returncode != 0:
            raise CodeBuilderError("Unable to execute the real Codex CLI")
        return result.stdout.strip()

    def _validate_base_commit(self) -> None:
        result = self._git(
            self.settings.source_repository,
            "cat-file",
            "-e",
            f"{self.settings.base_commit}^{{commit}}",
            check=False,
        )
        if result.returncode != 0:
            raise CodeBuilderError(f"Candidate base commit is unavailable: {self.settings.base_commit}")

    def _create_worktree(self, candidate_id: str) -> Path:
        self.settings.candidate_root.mkdir(parents=True, exist_ok=True)
        slug = _slug(candidate_id)
        workspace = self.settings.candidate_root / slug
        if workspace.exists():
            raise CodeBuilderError(f"Candidate workspace already exists: {workspace}")
        result = self._git(
            self.settings.source_repository,
            "worktree",
            "add",
            "--detach",
            str(workspace),
            self.settings.base_commit,
            check=False,
        )
        if result.returncode != 0:
            raise CodeBuilderError(f"Unable to create candidate worktree: {result.stderr.strip()}")
        if self._changed_paths(workspace):
            raise CodeBuilderError("Fresh candidate worktree is not clean")
        return workspace

    def _invoke_codex(
        self, executable: str, version: str, workspace: Path, prompt: str
    ) -> CodexExecution:
        writable_root = workspace / "services" / "detection" / "app"
        if not writable_root.is_dir():
            raise CodeBuilderError(f"Detection implementation root is missing: {writable_root}")
        argv = (
            executable,
            "--ask-for-approval",
            "never",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--json",
            "--color",
            "never",
            "--sandbox",
            "workspace-write",
            "-C",
            str(writable_root),
            "-",
        )
        try:
            result = self._run(
                argv,
                cwd=writable_root,
                timeout=self.settings.codex_timeout_seconds,
                input_text=prompt,
            )
        except subprocess.TimeoutExpired as exc:
            return CodexExecution(
                executable=executable,
                version=version,
                argv=argv[1:],
                exit_code=None,
                status="timed_out",
                stdout=_trim(_coerce_output(exc.stdout)),
                stderr=_trim(_coerce_output(exc.stderr)),
            )
        return CodexExecution(
            executable=executable,
            version=version,
            argv=argv[1:],
            exit_code=result.returncode,
            status="succeeded" if result.returncode == 0 else "failed",
            stdout=_trim(result.stdout),
            stderr=_trim(result.stderr),
        )

    def _implementation_prompt(
        self,
        *,
        objective: str,
        requested_behavior: str,
        required_signals: Sequence[str],
        known_risks: Sequence[str],
        allowed_paths: Sequence[str],
    ) -> str:
        protected_tests = "\n".join(f"- {path}" for path in self.settings.protected_test_paths)
        return f"""You are implementing one isolated Detection CODE candidate.

Evolution owns WHAT and WHY; you own HOW. Inspect the Detection implementation and implement the requested behavior. Do not change policy JSON or invent a CONFIG DSL.

Objective: {objective}
Requested behavior: {requested_behavior}
Required signals: {json.dumps(list(required_signals), ensure_ascii=False)}
Known risk to preserve: {json.dumps(list(known_risks), ensure_ascii=False)}

Behavioral acceptance:
- Trigger only when one seller-authored message contains both a payment-action signal and an extreme-discount or urgency inducement.
- Payment-only, inducement-only, buyer-authored, and negated/safety language remain clean.
- Never combine signals across separate messages.

You may modify ONLY these repository-relative paths:
{chr(10).join(f'- {path}' for path in allowed_paths)}

Do not create, delete, rename, stage, or commit files. Do not modify tests. Do not inspect evaluator, governance, evolution, validation/holdout manifests, ground truth, shared schemas, or environment seed data. Those are the exam and governance boundary.

You may read and run these protected behavioral tests, which are outside your writable root:
{protected_tests}

Work only inside the current candidate. Keep the change localized and deterministic. Run the protected acceptance test and the existing Detection tests before finishing. Do not report success unless the files are actually modified.
"""

    def _run_validations(self, workspace: Path) -> tuple[ValidationResult, ...]:
        results: list[ValidationResult] = []
        for command in self.settings.validation_commands:
            argv = tuple(_expand(value, workspace, self.settings.artifact_root) for value in command.argv)
            cwd = Path(_expand(command.cwd, workspace, self.settings.artifact_root))
            overrides = {
                key: _expand(value, workspace, self.settings.artifact_root)
                for key, value in command.environment
            }
            try:
                result = self._run(
                    argv,
                    cwd=cwd,
                    timeout=self.settings.validation_timeout_seconds,
                    environment=overrides,
                )
                status = "passed" if result.returncode == 0 else "failed"
                item = ValidationResult(
                    name=command.name,
                    argv=argv,
                    exit_code=result.returncode,
                    status=status,
                    stdout=_trim(result.stdout),
                    stderr=_trim(result.stderr),
                )
            except subprocess.TimeoutExpired as exc:
                item = ValidationResult(
                    name=command.name,
                    argv=argv,
                    exit_code=None,
                    status="timed_out",
                    stdout=_trim(_coerce_output(exc.stdout)),
                    stderr=_trim(_coerce_output(exc.stderr)),
                )
            results.append(item)
            if item.status != "passed":
                break
        return tuple(results)

    def _changed_paths(self, workspace: Path) -> tuple[str, ...]:
        tracked = self._git(
            workspace, "diff", "--name-only", "--diff-filter=ACDMRTUXB", "HEAD"
        ).stdout.splitlines()
        untracked = self._git(
            workspace, "ls-files", "--others", "--exclude-standard"
        ).stdout.splitlines()
        paths = tuple(sorted(set(filter(None, tracked + untracked))))
        for path in paths:
            if Path(path).is_absolute() or ".." in Path(path).parts:
                raise CodeBuilderError(f"Git reported an unsafe changed path: {path!r}")
        return paths

    def _working_patch_digest(self, workspace: Path) -> str:
        patch = self._git(workspace, "diff", "--binary", "HEAD").stdout.encode("utf-8")
        return hashlib.sha256(patch).hexdigest()

    def _protected_test_digests(self) -> dict[str, str]:
        digests: dict[str, str] = {}
        for path in self.settings.protected_test_paths:
            if not path.is_file():
                raise CodeBuilderError(f"Protected authoritative test is missing: {path}")
            digests[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return digests

    def _commit_candidate(
        self, workspace: Path, candidate_id: str, changed_paths: Sequence[str]
    ) -> str:
        self._git(workspace, "add", "--", *changed_paths)
        result = self._git(
            workspace,
            "-c",
            "user.name=Codex Candidate Builder",
            "-c",
            "user.email=codex-candidate@localhost",
            "commit",
            "-m",
            f"build(code): {_slug(candidate_id)}",
            check=False,
        )
        if result.returncode != 0:
            raise CodeBuilderError(f"Unable to commit immutable candidate: {result.stderr.strip()}")
        if self._changed_paths(workspace):
            raise CodeBuilderError("Candidate worktree is dirty after candidate commit")
        return self._git(workspace, "rev-parse", "HEAD").stdout.strip()

    def _publish_metadata(self, metadata: CodeCandidateMetadata) -> Path:
        self.settings.artifact_root.mkdir(parents=True, exist_ok=True)
        target = self.settings.artifact_root / f"{_slug(metadata.candidate_id)}.json"
        if target.exists():
            raise CodeBuilderError(f"Candidate metadata is immutable and already exists: {target}")
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(metadata.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return target

    def _git(
        self, cwd: Path, *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        result = self._run(("git", *arguments), cwd=cwd, timeout=120)
        if check and result.returncode != 0:
            raise CodeBuilderError(
                f"Git command failed ({' '.join(arguments)}): {result.stderr.strip()}"
            )
        return result

    def _run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
        input_text: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            key: value
            for key, value in self._environment.items()
            if key in _PASSTHROUGH_ENVIRONMENT or key.startswith("LC_")
        }
        env.update({"PYTHONUNBUFFERED": "1"})
        if environment:
            env.update(environment)
        return subprocess.run(
            tuple(argv),
            cwd=cwd,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )


def _slug(value: str) -> str:
    result = _SAFE_ID.sub("-", value).strip("-._")
    if not result:
        raise CodeBuilderError("Candidate identifier has no safe filesystem representation")
    return result[:120]


def _expand(value: str, workspace: Path, artifact_root: Path) -> str:
    return value.replace("{workspace}", str(workspace)).replace(
        "{artifact_root}", str(artifact_root)
    )


def _trim(value: str) -> str:
    if len(value) <= _OUTPUT_LIMIT:
        return value
    return value[:_OUTPUT_LIMIT] + "\n...[truncated by outer builder]"


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
