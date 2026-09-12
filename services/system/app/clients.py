from __future__ import annotations

from typing import Any

import httpx

from .settings import settings


async def run_detection(job: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "subject": job["subject"],
        "trigger_context": {
            "source": "api",
            "reason": job["trigger_ref"],
        },
    }
    requested_checks = job["payload"].get("requested_checks", [])
    if requested_checks:
        payload["requested_checks"] = requested_checks
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(f"{settings.detection_url}/detect", json=payload)
        response.raise_for_status()
        return response.json()


async def start_patrol(job: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "run_id": job["job_id"],
        "mode": "scheduled" if job["trigger_type"] == "schedule" else "manual",
        "strategy": job["payload"].get("strategy", "exploit"),
        "scope": job["payload"].get("scope", {"subject_types": []}),
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(f"{settings.patrol_url}/patrol/jobs", json=payload)
        response.raise_for_status()
        return response.json()


async def patrol_status(status_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.get(f"{settings.patrol_url}/{status_url.lstrip('/')}")
        response.raise_for_status()
        return response.json()


async def run_investigation(job: dict[str, Any]) -> dict[str, Any]:
    detection = dict(job["payload"]["detection_result"])
    detection.pop("policy_ref", None)
    detection.pop("component_results", None)
    payload = {
        "case_id": job["payload"]["case_id"],
        "detection_result": detection,
        "existing_evidence": job["payload"].get("existing_evidence", []),
        "scoreboard_config_ref": {
            "version": job["payload"].get(
                "scoreboard_config_version", settings.scoreboard_config_version
            )
        },
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(f"{settings.investigation_url}/investigate", json=payload)
        response.raise_for_status()
        return response.json()


async def start_association(job: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "case_id": job["payload"]["case_id"],
        "subject": job["subject"],
        "strategy": job["payload"].get("strategy", "focused"),
        "seed_indicators": job["payload"].get("seed_indicators", []),
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(
            f"{settings.association_url}/association/jobs", json=payload
        )
        response.raise_for_status()
        return response.json()


async def association_status(status_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.get(
            f"{settings.association_url}/{status_url.lstrip('/')}"
        )
        response.raise_for_status()
        return response.json()
