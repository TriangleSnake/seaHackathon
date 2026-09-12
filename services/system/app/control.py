from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from . import clients, storage
from .models import TriggerPolicy
from .settings import settings


class RuntimeState:
    def __init__(self) -> None:
        self.last_errors: dict[str, str] = {}

    def failed(self, loop: str, exc: Exception) -> None:
        self.last_errors[loop] = f"{type(exc).__name__}: {exc}"[:500]

    def healthy(self, loop: str) -> None:
        self.last_errors.pop(loop, None)


runtime_state = RuntimeState()


async def _forever(name: str, interval: int, operation: Callable[[], Awaitable[None]]) -> None:
    while True:
        try:
            await operation()
            runtime_state.healthy(name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            runtime_state.failed(name, exc)
        await asyncio.sleep(interval)


async def ingest_events_once() -> None:
    policies = [TriggerPolicy.model_validate(row) for row in await storage.list_trigger_policies(True)]
    for policy in policies:
        events = await storage.read_source_events(
            policy.source, policy.subject_id_field, policy.batch_size, cursor_key=policy.policy_id
        )
        for event in events:
            await storage.enqueue_event_job(policy, event)
            await storage.advance_cursor(policy.policy_id, event["occurred_at"], event["id"])


async def schedule_once() -> None:
    await storage.enqueue_due_schedule()


async def work_once() -> None:
    job = await storage.claim_job()
    if job is None:
        return
    try:
        if job["agent"] == "detection":
            if not job["subject"]:
                raise ValueError("Detection requires a subject")
            result = await clients.run_detection(job)
            await storage.complete_job(job["job_id"], result)
            if result.get("detected") is True and job["payload"].get("auto_investigate"):
                await storage.enqueue_child_job(
                    job,
                    "investigation",
                    result.get("subject"),
                    {
                        "case_id": f"case-{job['job_id']}",
                        "detection_result": result,
                        "routing": job["payload"].get("routing", {}),
                    },
                    str(result.get("detection_id", job["job_id"])),
                )
        elif job["agent"] == "patrol":
            accepted = await clients.start_patrol(job)
            await storage.dispatch_job(job["job_id"], accepted["job_id"], accepted["status_url"], accepted)
        elif job["agent"] == "investigation":
            result = await clients.run_investigation(job)
            await storage.complete_job(job["job_id"], result)
            routing = job["payload"].get("routing", {})
            depth = int(routing.get("association_depth", 0))
            max_depth = int(routing.get("max_association_depth", 2))
            if result.get("verdict") in {"fraud", "suspicious"} and depth < max_depth:
                await storage.enqueue_child_job(
                    job,
                    "association",
                    result.get("subject"),
                    {
                        "case_id": result["case_id"],
                        "strategy": "focused",
                        "routing": {
                            "association_depth": depth,
                            "max_association_depth": max_depth,
                        },
                    },
                    str(result["case_id"]),
                )
        elif job["agent"] == "association":
            accepted = await clients.start_association(job)
            await storage.dispatch_job(
                job["job_id"], accepted["job_id"], accepted["status_url"], accepted
            )
        else:
            raise ValueError(f"{job['agent']} dispatch is not connected in control-plane phase 1")
    except Exception as exc:
        await storage.fail_job(job, f"{type(exc).__name__}: {exc}")


async def reconcile_once() -> None:
    errors: list[str] = []
    for job in await storage.list_remote_jobs():
        try:
            remote = (
                await clients.patrol_status(job["remote_status_url"])
                if job["agent"] == "patrol"
                else await clients.association_status(job["remote_status_url"])
            )
            if remote["status"] == "completed":
                await storage.complete_job(job["job_id"], remote)
                if job["agent"] == "patrol":
                    result = remote.get("result") or {}
                    for discovery in result.get("discoveries", []):
                        await storage.enqueue_child_job(
                            job,
                            "detection",
                            discovery["subject"],
                            {
                                "patrol_discovery": discovery,
                                "requested_checks": [],
                                "auto_investigate": True,
                                "routing": {
                                    "association_depth": 0,
                                    "max_association_depth": 2,
                                },
                            },
                            f"{result.get('run_id')}:{discovery['subject']['type']}:{discovery['subject']['id']}",
                            policy_version=settings.detection_policy_version,
                        )
                elif job["agent"] == "association":
                    result = remote.get("result") or {}
                    routing = job["payload"].get("routing", {})
                    next_depth = int(routing.get("association_depth", 0)) + 1
                    max_depth = int(routing.get("max_association_depth", 2))
                    for related in result.get("related_subjects", []):
                        subject = related.get("subject")
                        if not subject or subject == job.get("subject"):
                            continue
                        await storage.enqueue_child_job(
                            job,
                            "detection",
                            subject,
                            {
                                "association_result": related,
                                "requested_checks": [],
                                "auto_investigate": True,
                                "routing": {
                                    "association_depth": next_depth,
                                    "max_association_depth": max_depth,
                                },
                            },
                            f"{result.get('case_id')}:{subject['type']}:{subject['id']}",
                            policy_version=settings.detection_policy_version,
                        )
            elif remote["status"] == "failed":
                await storage.fail_job(job, remote.get("error") or "Remote Patrol job failed")
        except Exception as exc:
            errors.append(f"{job['job_id']}: {type(exc).__name__}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors[:3]))


def background_tasks() -> list[asyncio.Task[None]]:
    tasks = [
        asyncio.create_task(_forever("event-ingest", settings.event_poll_seconds, ingest_events_once)),
        asyncio.create_task(_forever("schedule", settings.schedule_poll_seconds, schedule_once)),
        asyncio.create_task(_forever("remote-reconcile", settings.remote_poll_seconds, reconcile_once)),
    ]
    tasks.extend(
        asyncio.create_task(_forever(f"worker-{index + 1}", settings.worker_poll_seconds, work_once))
        for index in range(settings.max_concurrency)
    )
    return tasks
