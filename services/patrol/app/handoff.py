from __future__ import annotations

import asyncio
import os
from hashlib import sha256
from typing import Any

import httpx

from .models import PatrolDiscovery, PatrolResult


def _case_id(result: PatrolResult, discovery: PatrolDiscovery) -> str:
    key = f"{result.run_id}:{discovery.subject.type}:{discovery.subject.id}"
    return f"patrol-{sha256(key.encode()).hexdigest()[:20]}"


def build_investigation_payload(
    result: PatrolResult,
    discovery: PatrolDiscovery,
) -> dict[str, Any]:
    """Adapt one Patrol discovery to the currently published Investigation API."""
    evidence_by_id = {item.id: item for item in result.evidence}
    evidence = [evidence_by_id[item].model_dump(mode="json") for item in discovery.evidence_refs]
    trigger_context = {
        "source": "patrol",
        "run_id": result.run_id,
        "strategy": result.strategy,
        "policy_ref": result.policy_ref.model_dump(mode="json"),
        "hypothesis": discovery.hypothesis,
        "counter_signals": discovery.counter_signals,
        "priority": discovery.priority,
    }
    return {
        "case_id": _case_id(result, discovery),
        "detection_result": {
            "detection_id": f"patrol:{result.run_id}:{discovery.subject.id}",
            "subject": discovery.subject.model_dump(mode="json"),
            "detected": True,
            "triggers": [
                {
                    "type": signal.name,
                    "detector": "anomaly",
                    "reason": signal.description,
                    "raw_result": trigger_context,
                    "evidence_refs": signal.evidence_refs,
                }
                for signal in discovery.observed_signals
            ],
            "evidence": evidence,
        },
        "existing_evidence": [],
        "scoreboard_config_ref": {
            "version": os.environ.get("SCOREBOARD_CONFIG_VERSION", "development-v1")
        },
    }


async def handoff_to_investigation(result: PatrolResult) -> None:
    """Send every validated discovery to Investigation before completing the run."""
    if not result.discoveries:
        return
    base_url = os.environ.get("INVESTIGATION_URL", "http://investigation:8000").rstrip("/")
    timeout = float(os.environ.get("INVESTIGATION_TIMEOUT_SECONDS", "10"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        requests = [
            client.post(
                f"{base_url}/investigate",
                json=build_investigation_payload(result, discovery),
                headers={
                    "X-Request-ID": result.run_id,
                    "Idempotency-Key": _case_id(result, discovery),
                },
            )
            for discovery in result.discoveries
        ]
        responses = await asyncio.gather(*requests)
        for response in responses:
            response.raise_for_status()
