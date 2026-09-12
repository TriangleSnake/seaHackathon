"""One-command demo orchestration across discovery, synthesis, and evolution."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
from uuid import uuid4

import httpx

from services.evaluator.app.environment import PostgresEnvironmentControl
from services.integration.real_loop import SCENARIO, run_real_loop


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = REPOSITORY_ROOT / "runtime" / "demo-artifacts"


def _emit_stage(number: int, name: str, status: str, **details: Any) -> None:
    print(
        json.dumps(
            {"stage": number, "name": name, "status": status, "details": details},
            ensure_ascii=False,
        )
    )


def _load_service_package(alias: str, service: str) -> str:
    """Load a hyphenated service's app package without claiming a new contract."""

    if alias in sys.modules:
        return alias
    package_dir = REPOSITORY_ROOT / "services" / service / "app"
    spec = importlib.util.spec_from_file_location(
        alias,
        package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {service} application package")
    package = importlib.util.module_from_spec(spec)
    sys.modules[alias] = package
    spec.loader.exec_module(package)
    return alias


def collect_investigation_results(pipeline_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use Discovery Pipeline's shipped collector and return its stable documents."""

    alias = _load_service_package("_demo_discovery_pipeline", "discovery-pipeline")
    adapters = importlib.import_module(f"{alias}.adapters")
    models = importlib.import_module(f"{alias}.models")
    result = models.UpstreamPipelineResult.model_validate(pipeline_payload)
    handoff = adapters.collect_investigation_results(result)
    return [dict(item.investigation_result) for item in handoff]


def load_real_fixtures(paths: Sequence[Path]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict) and isinstance(
            payload.get("investigation_results"), list
        ):
            entries = payload["investigation_results"]
        else:
            entries = [payload]
        if any(not isinstance(item, dict) for item in entries):
            raise ValueError(f"Fixture {path} must contain InvestigationResult objects")
        results.extend(dict(item) for item in entries)
    return results


def build_synthesis_request(
    investigation_results: Sequence[Mapping[str, Any]],
    *,
    synthesis_id: str,
    grouping_reason: str,
    pattern_hint: str | None,
) -> dict[str, Any] | None:
    alias = _load_service_package("_demo_pattern_synthesis", "pattern-synthesis")
    models = importlib.import_module(f"{alias}.models")
    parsed = [models.InvestigationResult.model_validate(item) for item in investigation_results]
    candidates = [item for item in parsed if item.verdict in {"fraud", "suspicious"}]
    if not candidates:
        return None
    counterexamples = [item for item in parsed if item.verdict == "normal"]
    request = models.PatternSynthesisRequest(
        synthesis_id=synthesis_id,
        candidate_results=tuple(candidates),
        counterexample_results=tuple(counterexamples),
        active_defense_version={"version": "DV-001"},
        active_policy_refs=(
            {"type": "detection", "version": "baseline-v1"},
            {"type": "scoring", "version": "SP-001"},
            {"type": "exploration", "version": "EP-001"},
            {"type": "investigation", "version": "IP-001"},
            {"type": "association", "version": "AP-001"},
        ),
        policy_capability_summary={
            "summary": (
                "Detection supports exact substring matching over message.text; "
                "other behavior requires CODE."
            ),
            "capabilities": (
                {
                    "capability_id": "detection-flat-chat-phrases",
                    "policy_type": "detection",
                    "kind": "CONFIG",
                    "surface": "rule_based.chat_request_phrases",
                    "description": "Exact substring matching over each message.",
                    "constraints": (
                        "append_unique or remove only",
                        "no role-aware or compound conditions",
                    ),
                },
            ),
        },
        pattern_hint=pattern_hint,
        grouping_reason=grouping_reason,
    )
    return request.model_dump(mode="json")


def build_evolution_request(
    synthesis_request: Mapping[str, Any],
    synthesis_result: Mapping[str, Any],
) -> dict[str, Any]:
    alias = _load_service_package("_demo_pattern_synthesis", "pattern-synthesis")
    handoff_module = importlib.import_module(f"{alias}.handoff")
    models = importlib.import_module(f"{alias}.models")
    request = models.PatternSynthesisRequest.model_validate(synthesis_request)
    result = models.PatternSynthesisResult.model_validate(synthesis_result)
    return handoff_module.EvolutionHandoff().build_request(
        request,
        result,
        system_performance={},
    )


async def _post_json(url: str, payload: Mapping[str, Any], timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=dict(payload))
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"{url} returned HTTP {response.status_code}: {response.text[:500]}")
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f"{url} returned a non-object response")
    return value


async def _upstream_and_synthesis(
    args: argparse.Namespace,
    run_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    audit: dict[str, Any] = {"mode": args.mode, "run_id": run_id}
    if args.mode == "LIVE":
        patrol_request = {
            "run_id": run_id,
            "mode": "manual",
            "strategy": args.strategy,
            "scope": {"subject_types": args.subject_type},
        }
        pipeline = await _post_json(
            f"{args.discovery_pipeline_url.rstrip('/')}/pipeline/run",
            patrol_request,
            args.timeout,
        )
        audit["discovery_pipeline"] = pipeline
        patrol = pipeline["patrol"]
        discoveries = pipeline.get("discoveries", [])
        association_succeeded = sum(
            item.get("association", {}).get("status") == "succeeded"
            for item in discoveries
        )
        investigation_succeeded = sum(
            item.get("investigation", {}).get("status") == "succeeded"
            for item in discoveries
        )
        _emit_stage(
            1,
            "Patrol",
            patrol.get("status", "failed").upper(),
            discoveries=len(discoveries),
            legacy_direct_investigation="gated",
        )
        _emit_stage(
            2,
            "Association",
            "SUCCEEDED" if association_succeeded == len(discoveries) else "PARTIAL_OR_FAILED",
            succeeded=association_succeeded,
            total=len(discoveries),
        )
        _emit_stage(
            3,
            "Investigation",
            "SUCCEEDED" if investigation_succeeded == len(discoveries) else "PARTIAL_OR_FAILED",
            succeeded=investigation_succeeded,
            total=len(discoveries),
        )
        investigations = collect_investigation_results(pipeline)
        grouping_reason = "Grouped by one live Patrol run and successful Association lineage."
    else:
        investigations = load_real_fixtures(args.fixture)
        audit["real_fixture_paths"] = [str(path) for path in args.fixture]
        audit["investigation_results"] = investigations
        _emit_stage(1, "Patrol", "NOT_RUN", mode="REAL_FIXTURE")
        _emit_stage(2, "Association", "NOT_RUN", mode="REAL_FIXTURE")
        _emit_stage(
            3,
            "Investigation",
            "REAL_FIXTURE",
            loaded=len(investigations),
            live_call=False,
        )
        grouping_reason = "Explicit previously captured real InvestigationResult fixtures."

    request = build_synthesis_request(
        investigations,
        synthesis_id=f"SYN-{run_id}",
        grouping_reason=grouping_reason,
        pattern_hint=args.pattern_hint,
    )
    audit["pattern_synthesis_request"] = request
    if request is None:
        _emit_stage(
            4,
            "Pattern Synthesis",
            "NO_PATTERN",
            reason="No suspicious or fraud InvestigationResult was available.",
        )
        return None, audit

    synthesis = await _post_json(
        f"{args.pattern_synthesis_url.rstrip('/')}/synthesize",
        request,
        args.timeout,
    )
    audit["pattern_synthesis_result"] = synthesis
    _emit_stage(
        4,
        "Pattern Synthesis",
        synthesis.get("status", "FAILED"),
        reason=synthesis.get("reason"),
        candidate_cases=len(request["candidate_results"]),
    )
    if synthesis.get("status") == "NO_PATTERN":
        return None, audit
    evolution_request = build_evolution_request(request, synthesis)
    audit["evolution_request"] = evolution_request
    return evolution_request, audit


def _write_artifact(run_id: str, payload: Mapping[str, Any]) -> Path:
    root = Path(os.environ.get("DEMO_ARTIFACT_DIR", str(DEFAULT_ARTIFACT_DIR)))
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{run_id}.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return target


def _environment_preflight() -> Mapping[str, Any]:
    database_url = os.environ.get(
        "MEMBER4_DATABASE_URL",
        "postgresql://fraud:fraud_dev_password@127.0.0.1:55432/fraud_intelligence",
    )
    return PostgresEnvironmentControl(database_url).verify_isolated(SCENARIO)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("LIVE", "REAL_FIXTURE"), default="LIVE")
    parser.add_argument("--fixture", action="append", type=Path, default=[])
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument(
        "--discovery-pipeline-url", default="http://127.0.0.1:10006"
    )
    parser.add_argument(
        "--pattern-synthesis-url", default="http://127.0.0.1:10007"
    )
    parser.add_argument("--strategy", choices=("exploit", "explore"), default="explore")
    parser.add_argument(
        "--subject-type",
        action="append",
        choices=("account", "shop", "product", "transaction", "message"),
        default=[],
    )
    parser.add_argument("--pattern-hint")
    parser.add_argument("--run-id")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--human-approve", action="store_true")
    parser.add_argument("--disable-code-builder", action="store_true")
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.mode == "REAL_FIXTURE" and not args.fixture:
        parser.error("REAL_FIXTURE requires at least one --fixture path")
    run_id = args.run_id or f"demo-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    audit: dict[str, Any] = {"mode": args.mode, "run_id": run_id}
    try:
        environment = _environment_preflight()
        audit["environment"] = environment
        _emit_stage(0, "Environment", "VERIFIED", scenario=SCENARIO)
        evolution_request, upstream_audit = asyncio.run(
            _upstream_and_synthesis(args, run_id)
        )
        audit.update(upstream_audit)
        if evolution_request is None:
            audit["strongest_success_level"] = 1
            artifact = _write_artifact(run_id, audit)
            print(json.dumps({"result": "STOPPED_GRACEFULLY", "artifact": str(artifact)}))
            return 0

        evolution = run_real_loop(
            args.env_file,
            human_approve=args.human_approve,
            evolution_request=evolution_request,
            code_builder_enabled=not args.disable_code_builder,
        )
        audit["evolution"] = evolution
        _emit_stage(
            5,
            "Evolution",
            evolution.get("terminal_state", "UNKNOWN"),
            openai_live_call=evolution.get("openai_live_call_occurred", False),
        )
        mode = evolution.get("resolver_mode")
        _emit_stage(6, "Capability Resolver", mode or "NO_CANDIDATE")
        candidate = evolution.get("candidate_result")
        _emit_stage(
            7,
            "Candidate Build",
            candidate.get("status", "NOT_BUILT") if isinstance(candidate, Mapping) else "NOT_BUILT",
            candidate_id=candidate.get("candidate_id") if isinstance(candidate, Mapping) else None,
        )
        if mode == "CODE":
            code_result = evolution.get("code_build_validation") or {}
            _emit_stage(
                8,
                "Codex Builder",
                str(code_result.get("status", "not_run")).upper(),
                label="CODE BUILD / VALIDATION",
                full_evaluator_closed_loop=False,
            )
            level = 2
        else:
            validations = evolution.get("validations") or []
            validation = validations[-1] if validations else None
            _emit_stage(
                8,
                "Evaluator",
                validation.get("status", "NOT_RUN") if validation else "NOT_RUN",
                metrics=validation.get("candidate_metrics") if validation else None,
            )
            level = 4 if evolution.get("governance") else (3 if validation else 2)
        audit["strongest_success_level"] = level
        artifact = _write_artifact(run_id, audit)
        print(
            json.dumps(
                {
                    "result": "COMPLETE",
                    "mode": args.mode,
                    "resolver_mode": mode,
                    "strongest_success_level": level,
                    "artifact": str(artifact),
                }
            )
        )
        return 0
    except Exception as exc:
        secret = os.environ.get("OPENAI_API_KEY", "")
        message = str(exc).replace(secret, "[REDACTED]") if secret else str(exc)
        audit["fatal_error"] = {"type": type(exc).__name__, "message": message}
        artifact = _write_artifact(run_id, audit)
        print(
            json.dumps(
                {
                    "result": "FAILED",
                    "error": audit["fatal_error"],
                    "artifact": str(artifact),
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
