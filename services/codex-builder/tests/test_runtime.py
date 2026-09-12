from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from codex_builder.models import ValidationCommand
from codex_builder.runtime import CodeBuilderSettings, RealCodexCodeBuilder


ALLOWED = (
    "services/detection/app/repository.py",
    "services/detection/app/detectors/rules.py",
)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "source"
    (repository / "services/detection/app/detectors").mkdir(parents=True)
    (repository / "services/detection/app/repository.py").write_text("BASE = 1\n")
    (repository / "services/detection/app/detectors/rules.py").write_text("BASE = 1\n")
    (repository / "services/detection/app/service.py").write_text("BASE = 1\n")
    _git(repository, "init", "-q")
    _git(repository, "add", ".")
    _git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "base",
    )
    return repository, _git(repository, "rev-parse", "HEAD")


def _fake_codex(tmp_path: Path, body: str) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('codex-cli test')\n"
        "    raise SystemExit(0)\n"
        "root = pathlib.Path(sys.argv[sys.argv.index('-C') + 1])\n"
        "_prompt = sys.stdin.read()\n"
        + body
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _settings(
    tmp_path: Path,
    repository: Path,
    base: str,
    executable: Path,
    *,
    command: ValidationCommand | None = None,
) -> tuple[CodeBuilderSettings, Path]:
    protected = tmp_path / "protected_acceptance.py"
    protected.write_text("# immutable exam\n")
    validation = command or ValidationCommand(
        name="acceptance",
        argv=(sys.executable, "-c", "print('acceptance passed')"),
    )
    return (
        CodeBuilderSettings(
            source_repository=repository,
            base_commit=base,
            candidate_root=tmp_path / "candidates",
            artifact_root=tmp_path / "artifacts",
            protected_test_paths=(protected,),
            validation_commands=(validation,),
            codex_executable=str(executable),
            validation_timeout_seconds=30,
            codex_timeout_seconds=30,
        ),
        protected,
    )


def _build(settings: CodeBuilderSettings, candidate: str = "code-candidate-test"):
    return RealCodexCodeBuilder(
        settings,
        process_environment={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "OPENAI_API_KEY": "must-not-reach-codex",
        },
    ).build(
        build_id="build-test",
        candidate_id=candidate,
        objective="Detect compound behavior",
        requested_behavior="Require role, payment, and inducement together",
        required_signals=("sender.role", "message.payment", "message.inducement"),
        known_risks=("legitimate promotions",),
        allowed_paths=ALLOWED,
    )


def test_successful_build_commits_only_allowed_diff_and_publishes_metadata(
    tmp_path: Path,
) -> None:
    repository, base = _repository(tmp_path)
    executable = _fake_codex(
        tmp_path,
        "(root / 'repository.py').write_text('BASE = 2\\n')\n"
        "print('{\"type\":\"item.completed\"}')\n",
    )
    settings, _ = _settings(tmp_path, repository, base, executable)

    result = _build(settings)

    assert result.success is True
    metadata = result.metadata
    assert metadata.base_commit == base
    assert metadata.codex.status == "succeeded"
    assert metadata.codex.argv[:3] == ("--ask-for-approval", "never", "exec")
    assert metadata.changed_paths == ("services/detection/app/repository.py",)
    assert metadata.path_boundary_valid is True
    assert metadata.protected_tests_unchanged is True
    assert metadata.test_status == "passed"
    assert metadata.candidate_commit
    assert _git(Path(metadata.candidate_workspace or ""), "status", "--porcelain") == ""
    payload = json.loads(Path(result.metadata_path).read_text())
    assert payload["candidate_commit"] == metadata.candidate_commit
    assert "OPENAI_API_KEY" not in json.dumps(payload)
    assert "must-not-reach-codex" not in json.dumps(payload)
    assert "DETECTION_CANDIDATE_ROOT" not in metadata.codex.argv


def test_forbidden_path_change_fails_closed_before_tests(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path)
    executable = _fake_codex(
        tmp_path,
        "(root / 'service.py').write_text('BASE = 2\\n')\n",
    )
    marker = tmp_path / "validation-ran"
    command = ValidationCommand(
        name="must_not_run",
        argv=(sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"),
    )
    settings, _ = _settings(
        tmp_path, repository, base, executable, command=command
    )

    result = _build(settings)

    assert result.success is False
    assert result.metadata.path_boundary_valid is False
    assert "forbidden paths" in (result.metadata.failure_reason or "")
    assert marker.exists() is False
    assert result.metadata.candidate_commit is None


def test_protected_test_change_is_rejected(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path)
    protected = tmp_path / "protected_acceptance.py"
    executable = _fake_codex(
        tmp_path,
        f"pathlib.Path({str(protected)!r}).write_text('tampered\\n')\n"
        "(root / 'repository.py').write_text('BASE = 2\\n')\n",
    )
    settings, actual_protected = _settings(tmp_path, repository, base, executable)
    assert actual_protected == protected

    result = _build(settings)

    assert result.success is False
    assert result.metadata.protected_tests_unchanged is False
    assert "protected authoritative test changed" in (
        result.metadata.failure_reason or ""
    ).lower()


def test_authoritative_validation_failure_rejects_candidate(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path)
    executable = _fake_codex(
        tmp_path, "(root / 'repository.py').write_text('BASE = 2\\n')\n"
    )
    command = ValidationCommand(
        name="authoritative_acceptance",
        argv=(sys.executable, "-c", "raise SystemExit(3)"),
    )
    settings, _ = _settings(
        tmp_path, repository, base, executable, command=command
    )

    result = _build(settings)

    assert result.success is False
    assert result.metadata.path_boundary_valid is True
    assert result.metadata.test_status == "failed"
    assert result.metadata.tests[0].exit_code == 3
    assert result.metadata.candidate_commit is None


def test_runtime_rejects_a_broader_directive_boundary(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path)
    executable = _fake_codex(tmp_path, "raise SystemExit(0)\n")
    settings, _ = _settings(tmp_path, repository, base, executable)
    builder = RealCodexCodeBuilder(settings)

    result = builder.build(
        build_id="build-test",
        candidate_id="code-candidate-test",
        objective="test",
        requested_behavior="test",
        required_signals=(),
        known_risks=(),
        allowed_paths=ALLOWED + ("services/detection/app/service.py",),
    )

    assert result.success is False
    assert result.metadata.candidate_workspace is None
    assert "does not match" in (result.metadata.failure_reason or "")


def test_acceptance_spec_fails_on_the_integration_baseline() -> None:
    acceptance = (
        SERVICE_ROOT / "tests/acceptance/seller_conditional_payment_acceptance.py"
    )
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            str(acceptance),
        ),
        cwd=SERVICE_ROOT.parent / "detection" / "app",
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(SERVICE_ROOT.parent / "detection"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "test_seller_payment_and_extreme_discount_triggers" in result.stdout
