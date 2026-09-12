"""Outer, read-only live smoke. Never passed to runtime Codex; not an evaluator."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.evaluator.app.environment import PostgresEnvironmentControl
from services.detection.app.settings import Settings

BASE = "96ab1e05c8f8d9e721816cabdf92d6fdde01e13c"
SCENARIO = "taiwan-marketplace-20260912"
FROZEN = datetime.fromisoformat("2026-09-10T12:00:00+08:00")


def git(workspace, *args):
    return subprocess.check_output(("git", *args), cwd=workspace, text=True).strip()


def isolated_url():
    configured = os.environ.get("MEMBER4_DATABASE_URL")
    if configured:
        return configured
    # Reuse the repository's dummy local development credentials, never print.
    parsed = urlsplit(Settings.from_env().database_url)
    userinfo = parsed.netloc.rsplit("@", 1)[0]
    return urlunsplit((parsed.scheme, userinfo + "@127.0.0.1:55432", parsed.path, "", ""))


def verify_snapshot(environment):
    snapshot = environment.verify_isolated(SCENARIO)
    if datetime.fromisoformat(snapshot["simulation"]["simulation_time"]) != FROZEN:
        raise RuntimeError("Environment is not at the required frozen time; refusing to change it")
    return snapshot


@contextmanager
def server(workspace: Path, database_url: str):
    # Pass an already bound socket so there is no free-port discovery race.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "LANG", "HOME", "TMPDIR")}
    env.update(DATABASE_URL=database_url, PGOPTIONS="-c default_transaction_read_only=on",
               PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(workspace / "services/detection"),
               DETECTION_POLICY_DIR=str(workspace / "services/detection/config/policies"))
    process = subprocess.Popen(
        (sys.executable, "-m", "uvicorn", "app.main:app", "--fd", str(listener.fileno()), "--log-level", "error"),
        cwd=workspace / "services/detection", env=env, pass_fds=(listener.fileno(),),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    listener.close()
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Detection server failed to start")
            try:
                with urlopen(f"http://127.0.0.1:{port}/ready", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Detection server did not become ready")
        yield port
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def detect(port, identifier):
    payload = {"subject": {"type": "message", "id": identifier}, "requested_checks": ["rule_based"],
               "policy_ref": {"type": "detection", "version": "baseline-v1"}}
    request = Request(f"http://127.0.0.1:{port}/detect", data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        if response.headers.get("X-Detection-Policy-Version") != "baseline-v1":
            raise RuntimeError("Policy provenance changed")
        value = json.load(response)
    return {"detected": value["detected"], "trigger_count": len(value["triggers"]),
            "trigger_evidence": [item["evidence_refs"] for item in value["triggers"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--controls", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Live evidence output is immutable")
    metadata = json.loads(args.metadata.read_text())
    if metadata["status"] != "built" or metadata["test_status"] != "passed" or not metadata["path_boundary_valid"]:
        raise RuntimeError("Only a passed code candidate may enter the live smoke")
    candidate = Path(metadata["candidate_workspace"])
    if git(candidate, "rev-parse", "HEAD") != metadata["candidate_commit"] or git(candidate, "status", "--porcelain"):
        raise RuntimeError("Candidate is not the clean immutable tested commit")
    if git(args.baseline, "rev-parse", "HEAD:services/detection") != git(args.baseline, "rev-parse", f"{BASE}:services/detection"):
        raise RuntimeError("Baseline Detection does not match the exact integration base")
    if git(args.baseline, "status", "--porcelain", "--", "services/detection"):
        raise RuntimeError("Baseline Detection is dirty")
    policy = "services/detection/config/policies/baseline-v1.json"
    if (candidate / policy).read_bytes() != (args.baseline / policy).read_bytes():
        raise RuntimeError("Baseline and code candidate policies differ")
    database_url = isolated_url()
    environment = PostgresEnvironmentControl(database_url)
    before = verify_snapshot(environment)  # First DB operation; no clock setter.
    observations = {}
    with server(args.baseline, database_url) as baseline_port, server(candidate, database_url) as candidate_port:
        for identifier in ["MSG-0916", *args.controls]:
            if verify_snapshot(environment) != before:
                raise RuntimeError("Snapshot changed during smoke")
            observations[identifier] = {"baseline": detect(baseline_port, identifier),
                                        "candidate": detect(candidate_port, identifier)}
    after = verify_snapshot(environment)
    if before != after:
        raise RuntimeError("Snapshot changed during smoke")
    passed = not observations["MSG-0916"]["baseline"]["detected"] and observations["MSG-0916"]["candidate"]["detected"]
    passed = passed and all(not row[engine]["detected"] for key,row in observations.items() if key != "MSG-0916" for engine in ("baseline","candidate"))
    result = {"status": "passed" if passed else "failed", "scope": "live rule_based HTTP smoke, not EvaluationResult",
              "candidate_id": metadata["candidate_id"], "engine_commit": metadata["candidate_commit"],
              "baseline_engine_commit": BASE, "policy_version": "baseline-v1",
              "policy_sha256": hashlib.sha256((candidate / policy).read_bytes()).hexdigest(),
              "snapshot_before": before, "snapshot_after": after, "observations": observations,
              "evaluation_adapter": "missing engine-version dimension; no policy_ref substitution"}
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
