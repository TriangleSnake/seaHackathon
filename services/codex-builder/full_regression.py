"""Run all Detection tests against a disposable seed database, never port 55432."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid

from codex_builder.runtime import CodeBuilderSettings
from codex_builder.container_runtime import DockerCodexCodeBuilder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Regression evidence is immutable")
    metadata = json.loads(args.metadata.read_text())
    if metadata["status"] != "built":
        raise RuntimeError("A built candidate is required")
    workspace = Path(metadata["candidate_workspace"])
    source = Path(__file__).resolve().parents[2]
    settings = CodeBuilderSettings.for_detection(source_repository=source, base_commit=metadata["base_commit"],
        candidate_root=workspace.parent, artifact_root=args.output.parent,
        acceptance_test=source / "services/codex-builder/tests/acceptance/seller_conditional_payment_acceptance.py")
    builder = DockerCodexCodeBuilder(settings)
    builder._resolve_codex_executable()
    if builder._git(workspace, "rev-parse", "HEAD").stdout.strip() != metadata["candidate_commit"] or builder._changed_paths(workspace):
        raise RuntimeError("Candidate differs from its tested immutable commit")
    name = "m4-regression-" + uuid.uuid4().hex[:12]
    password = secrets.token_hex(24)
    env = {**os.environ, "POSTGRES_PASSWORD": password}
    test_name = None

    def docker(*parts, check=True):
        result = subprocess.run(("docker", *parts), env=env, capture_output=True, text=True, timeout=60)
        if check and result.returncode:
            raise RuntimeError(result.stderr.replace(password, "[REDACTED]"))
        return result

    try:
        docker("network", "create", "--internal", name)
        docker("run", "--rm", "-d", "--name", name, "--network", name,
               "--tmpfs", "/var/lib/postgresql/data:rw,size=512m", "-e", "POSTGRES_PASSWORD",
               "-e", "POSTGRES_USER=fraud", "-e", "POSTGRES_DB=fraud_intelligence",
               "--mount", f"type=bind,src={workspace / 'environment/schema.sql'},dst=/docker-entrypoint-initdb.d/001-schema.sql,readonly",
               "--mount", f"type=bind,src={workspace / 'environment/seed.sql'},dst=/docker-entrypoint-initdb.d/002-seed.sql,readonly",
               "postgres:16-alpine")
        for _ in range(90):
            # TCP readiness avoids the temporary socket-only init server.
            if docker("exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "fraud", "-d", "fraud_intelligence", check=False).returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable regression database did not become ready")
        argv = list(builder._container(workspace, writable=False, cwd=workspace / "services/detection"))
        test_name = argv[argv.index("--name") + 1]
        argv[argv.index("--network") + 1] = name
        argv[-1:-1] = ["-e", "DETECTION_TEST_DATABASE_URL"]
        env["DETECTION_TEST_DATABASE_URL"] = f"postgresql://fraud:{password}@{name}:5432/fraud_intelligence"
        result = subprocess.run((*argv, "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"),
                                capture_output=True, text=True, env=env, timeout=180)
        report = {"candidate_id": metadata["candidate_id"], "candidate_commit": metadata["candidate_commit"],
                  "status": "passed" if result.returncode == 0 else "failed", "exit_code": result.returncode,
                  "database": "disposable internal-network container; no host port; removed after test",
                  "stdout": result.stdout.replace(password, "[REDACTED]"),
                  "stderr": result.stderr.replace(password, "[REDACTED]")}
        with args.output.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(json.dumps(report, indent=2))
        return result.returncode
    finally:
        if test_name:
            docker("rm", "-f", test_name, check=False)
        docker("rm", "-f", name, check=False)
        docker("network", "rm", name, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
