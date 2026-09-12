from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from hashlib import sha256

from .agent import run_patrol
from .handoff import handoff_to_investigation
from .models import PatrolJobAccepted, PatrolJobState, PatrolPolicy, PatrolRequest, PatrolResult, PatrolScope
from .policy import load_active_policy
from .storage import claim_due_schedules, get_job as load_job, list_jobs as load_jobs, put_job


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_id(request: PatrolRequest, policy: PatrolPolicy) -> str:
    identity = json.dumps({"request": request.model_dump(mode="json"), "policy_id": policy.policy_id, "policy_version": policy.version}, sort_keys=True, separators=(",", ":"))
    return f"patrol-{sha256(identity.encode()).hexdigest()[:24]}"


class PatrolJobManager:
    def __init__(self) -> None:
        concurrency = max(1, min(int(os.environ.get("PATROL_MAX_CONCURRENCY", "2")), 10))
        self._semaphore = asyncio.Semaphore(concurrency)
        self._jobs: dict[str, PatrolJobState] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    async def submit(self, request: PatrolRequest, policy: PatrolPolicy) -> PatrolJobAccepted:
        job_id = _job_id(request, policy)
        existing = await self.get(job_id)
        if existing is None or existing.status == "failed":
            now = _now()
            job = PatrolJobState(job_id=job_id, status="queued", run_id=request.run_id, strategy=request.strategy,
                policy_ref={"id": policy.policy_id, "version": policy.version}, created_at=now, updated_at=now,
                handoff_status="pending")
            async with self._lock:
                self._jobs[job_id] = job
            await put_job(job_id, request.model_dump(mode="json"), job.model_dump(mode="json"))
            task = asyncio.create_task(self._execute(job_id, request, policy))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            status = "queued"
        else:
            status = existing.status
        return PatrolJobAccepted(job_id=job_id, status=status, status_url=f"/patrol/jobs/{job_id}")

    async def get(self, job_id: str) -> PatrolJobState | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return job.model_copy(deep=True)
        stored = await load_job(job_id)
        return PatrolJobState.model_validate(stored) if stored else None

    async def list(self, limit: int = 50) -> list[PatrolJobState]:
        return [PatrolJobState.model_validate(item) for item in await load_jobs(limit)]

    async def retry_handoff(self, job_id: str) -> PatrolJobState | None:
        job = await self.get(job_id)
        if job is None or job.status != "completed" or job.result is None or not job.result.discoveries:
            return job
        async with self._lock:
            self._jobs[job_id] = job
        await self._update(job_id, handoff_status="pending", error=None)
        await self._handoff(job_id, job.result)
        return await self.get(job_id)

    async def _update(self, job_id: str, **changes: object) -> None:
        async with self._lock:
            job = self._jobs[job_id]
            job = job.model_copy(update={**changes, "updated_at": _now()}, deep=True)
            self._jobs[job_id] = job
        await put_job(job_id, {}, job.model_dump(mode="json"))

    async def _execute(self, job_id: str, request: PatrolRequest, policy: PatrolPolicy) -> None:
        async with self._semaphore:
            await self._update(job_id, status="running")
            try:
                result = await run_patrol(request, policy)
                await self._update(job_id, status="completed", result=result,
                    handoff_status="pending" if result.discoveries else "not_required")
            except Exception as exc:
                await self._update(job_id, status="failed", error=f"Patrol run failed: {type(exc).__name__}")
                return
            if not result.discoveries:
                return
            await self._handoff(job_id, result)

    async def _handoff(self, job_id: str, result: PatrolResult) -> None:
        job = await self.get(job_id)
        attempts = (job.handoff_attempts if job else 0) + 1
        try:
            await handoff_to_investigation(result)
            await self._update(job_id, handoff_status="delivered", handoff_attempts=attempts)
        except Exception as exc:
            await self._update(job_id, handoff_status="failed", handoff_attempts=attempts,
                error=f"Investigation handoff failed: {type(exc).__name__}")


async def scheduler_loop(manager: PatrolJobManager) -> None:
    while True:
        for schedule in await claim_due_schedules():
            strategy = schedule["strategy"]
            request = PatrolRequest(run_id=f"scheduled-{strategy}-{uuid.uuid4().hex[:16]}", mode="scheduled",
                strategy=strategy, scope=PatrolScope.model_validate(schedule["scope"]))
            await manager.submit(request, load_active_policy(strategy))
        await asyncio.sleep(max(5, int(os.environ.get("PATROL_SCHEDULER_POLL_SECONDS", "15"))))


job_manager = PatrolJobManager()
