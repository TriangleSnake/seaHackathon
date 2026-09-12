"""Real Codex in a mount-isolated container; host Git stays in the outer builder."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from .models import CodexExecution
from .runtime import RealCodexCodeBuilder, CodeBuilderError, _trim, _coerce_output


class DockerCodexCodeBuilder(RealCodexCodeBuilder):
    def __init__(self, settings, *, image="member4-real-codex-builder:0.154.0", **kwargs):
        super().__init__(settings, **kwargs)
        self.image = image
        self.image_id = None

    def _resolve_codex_executable(self):
        result = self._run(("docker", "image", "inspect", self.image, "--format", "{{.Id}}"),
                           cwd=self.settings.source_repository, timeout=30)
        if result.returncode:
            raise CodeBuilderError("Dedicated Codex container image is unavailable")
        self.image_id = result.stdout.strip()
        return "codex"

    def _codex_version(self, executable):
        result = self._run(("docker", "run", "--rm", "--network", "none", self.image_id,
                            executable, "--version"), cwd=self.settings.source_repository, timeout=30)
        if result.returncode:
            raise CodeBuilderError("Real Linux Codex executable is unavailable")
        return result.stdout.strip()

    def _container(self, workspace, *, writable, network=False, auth=False, cwd=None, name=None):
        args = ["docker", "run", "--rm", "-i", "--read-only", "--cap-drop=ALL", "--user", f"{os.getuid()}:{os.getgid()}",
                "--security-opt", "no-new-privileges", "--security-opt", "seccomp=unconfined", "--pids-limit", "256",
                "--memory", "2g", "--cpus", "2", "--network", "bridge" if network else "none",
                "--tmpfs", "/tmp:rw,nosuid,size=256m", "--tmpfs", "/codex-home:rw,nosuid,size=128m"]
        args += ["--name", name or "m4-code-" + uuid.uuid4().hex[:16]]
        detection = workspace / "services/detection"
        args += ["--mount", f"type=bind,src={detection},dst={detection},readonly"]
        if writable:
            for path in self.settings.allowed_paths:
                args += ["--mount", f"type=bind,src={workspace / path},dst={workspace / path}"]
        for exam in self.settings.protected_test_paths:
            args += ["--mount", f"type=bind,src={exam},dst={exam},readonly"]
        if auth:
            auth_path = Path(self._environment.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
            if not auth_path.is_file():
                raise CodeBuilderError("Codex account login file unavailable; no API-key fallback")
            args += ["--mount", f"type=bind,src={auth_path},dst=/codex-home/auth.json,readonly"]
        args += ["-e", f"PYTHONPATH={detection}", "-e", f"DETECTION_CANDIDATE_ROOT={detection}",
                 "-w", str(cwd or workspace), self.image_id]
        return tuple(args)

    def _permissions(self, workspace):
        # The immutable container/mount table is the write authority. This
        # inner namespace masks credentials and blocks network without asking
        # bwrap to synthesize metadata children beneath a regular file.
        files = {"/": "write", "/codex-home/auth.json": "deny"}
        entries = ", ".join(f"{json.dumps(k)}={json.dumps(v)}" for k, v in files.items())
        return ("-c", 'default_permissions="candidate"', "-c", f"permissions.candidate.filesystem={{ {entries} }}",
                "-c", "permissions.candidate.network.enabled=false", "-c", 'web_search="disabled"',
                "-c", 'shell_environment_policy.inherit="none"',
                "-c", 'shell_environment_policy.set.PYTHONDONTWRITEBYTECODE="1"',
                "-c", 'features.apps=false', "-c", 'features.multi_agent=false')

    def _verify_sandbox(self, executable, workspace):
        allowed = [str(workspace / p) for p in self.settings.allowed_paths]
        exams = [str(p) for p in self.settings.protected_test_paths]
        readonly = [str(workspace / "services/detection/app/service.py"),
                    str(workspace / "services/detection/config/policies/baseline-v1.json"), *exams]
        absent = [str(workspace / p) for p in ("services/evaluator", "environment", ".git", "shared/schemas")]
        probe = f'''import os, errno, socket
for p in {readonly!r}:
    with open(p, 'rb') as f: f.read(1)
    try: fd=os.open(p, os.O_WRONLY)
    except OSError as e: assert e.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
    else: os.close(fd); raise RuntimeError('protected write allowed: ' + p)
for p in {allowed!r}:
    fd=os.open(p, os.O_WRONLY); os.close(fd)
for p in {absent!r}: assert not os.path.exists(p), p
try: open('/codex-home/auth.json','rb')
except PermissionError: pass
else: raise RuntimeError('authentication readable by model tools')
try: socket.socket().connect(('1.1.1.1',443))
except OSError as e: assert e.errno in (errno.EPERM, errno.EACCES), e
else: raise RuntimeError('model tool network allowed')
print('filesystem boundary probe passed')
'''
        args = (*self._container(workspace, writable=True, auth=True, network=True), executable,
                *self._permissions(workspace), "sandbox", "-P", "candidate", "-C", str(workspace),
                "python", "-c", probe)
        result = self._run(args, cwd=workspace, timeout=30)
        if result.returncode or "filesystem boundary probe passed" not in result.stdout:
            raise CodeBuilderError(f"Container isolation probe failed ({result.returncode}): {result.stderr[-3000:]}")

    def _invoke_codex(self, executable, version, workspace, prompt):
        name = "m4-code-" + uuid.uuid4().hex[:16]
        argv = (*self._container(workspace, writable=True, network=True, auth=True, name=name),
                executable, "--ask-for-approval", "never", *self._permissions(workspace),
                "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
                "--json", "--color", "never", "-C", str(workspace), "-")
        prompt = prompt.replace(sys.executable, "/usr/local/bin/python")
        try:
            result = self._run(argv, cwd=workspace, timeout=self.settings.codex_timeout_seconds, input_text=prompt)
            return CodexExecution(executable=f"{self.image_id}:codex", version=version, argv=argv,
                                  exit_code=result.returncode, status="succeeded" if result.returncode == 0 else "failed",
                                  stdout=_trim(result.stdout), stderr=_trim(result.stderr))
        except subprocess.TimeoutExpired as exc:
            return CodexExecution(executable=executable, version=version, argv=argv, exit_code=None,
                                  status="timed_out", stdout=_trim(_coerce_output(exc.stdout)), stderr="Codex timeout")
        finally:
            # Kill only this uniquely named disposable build container, including descendants.
            self._run(("docker", "rm", "-f", name), cwd=workspace, timeout=30)

    def _validation_invocation(self, workspace, name, argv, cwd, environment):
        if name == "git_diff_check":
            return argv, cwd, environment
        argv = tuple("python" if value == sys.executable else value for value in argv)
        return (*self._container(workspace, writable=False, cwd=cwd), *argv), workspace, {}

    def _run(self, argv, **kwargs):
        try:
            return super()._run(argv, **kwargs)
        except subprocess.TimeoutExpired:
            if tuple(argv[:2]) == ("docker", "run") and "--name" in argv:
                name = argv[argv.index("--name") + 1]
                if name.startswith("m4-code-"):
                    super()._run(("docker", "rm", "-f", name), cwd=kwargs["cwd"], timeout=30)
            raise
