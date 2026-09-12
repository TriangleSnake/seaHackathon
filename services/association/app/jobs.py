from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from hashlib import sha256

import httpx

from .agent import run_association
from .models import (
    AssociationJobAccepted,
    AssociationJobState,
    AssociationPolicy,
    AssociationRequest,
    PolicyRef,
)
from .storage import get_job as load_job
from .storage import list_jobs as load_jobs
from .storage import put_job, record_callback_attempt


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_id(request: AssociationRequest, policy: AssociationPolicy) -> str:
    identity = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "policy_id": policy.policy_id,
            "policy_version": policy.version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"assoc-{sha256(identity.encode()).hexdigest()[:24]}"


class AssociationJobManager:
    """Single-process job runner; replace the store with durable System storage later."""

    def __init__(self) -> None:
        concurrency = max(1, min(int(os.environ.get("ASSOCIATION_MAX_CONCURRENCY", "2")), 10))
        self._semaphore = asyncio.Semaphore(concurrency)
        self._jobs: dict[str, AssociationJobState] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    async def submit(
        self,
        request: AssociationRequest,
        policy: AssociationPolicy,
    ) -> AssociationJobAccepted:
        job_id = _job_id(request, policy)
        async with self._lock:
            existing = self._jobs.get(job_id)
            if existing is None or existing.status == "failed":
                now = _now()
                callback_status = (
                    "pending" if os.environ.get("ASSOCIATION_RESULT_URL", "").strip()
                    else "not_configured"
                )
                self._jobs[job_id] = AssociationJobState(
                    job_id=job_id,
                    status="queued",
                    case_id=request.case_id,
                    strategy=request.strategy,
                    policy_ref=PolicyRef(id=policy.policy_id, version=policy.version),
                    created_at=now,
                    updated_at=now,
                    callback_status=callback_status,
                )
                await put_job(
                    job_id,
                    request.model_dump(mode="json"),
                    self._jobs[job_id].model_dump(mode="json"),
                )
                task = asyncio.create_task(self._execute(job_id, request, policy))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            status = self._jobs[job_id].status
        return AssociationJobAccepted(
            job_id=job_id,
            status=status,
            status_url=f"/association/jobs/{job_id}",
        )

    async def get(self, job_id: str) -> AssociationJobState | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return job.model_copy(deep=True)
        stored = await load_job(job_id)
        return AssociationJobState.model_validate(stored) if stored else None

    async def list(self, limit: int = 50) -> list[AssociationJobState]:
        return [AssociationJobState.model_validate(item) for item in await load_jobs(limit)]

    async def retry_callback(self, job_id: str) -> AssociationJobState | None:
        job = await self.get(job_id)
        if job is None or job.status != "completed" or job.result is None:
            return job
        async with self._lock:
            self._jobs[job_id] = job
        await self._update(job_id, callback_status="pending")
        await self._deliver_callback(job_id)
        return await self.get(job_id)

    async def _execute(
        self,
        job_id: str,
        request: AssociationRequest,
        policy: AssociationPolicy,
    ) -> None:
        async with self._semaphore:
            await self._update(job_id, status="running")
            try:
                result = await run_association(request, policy)
                await self._update(job_id, status="completed", result=result)
                await self._deliver_callback(job_id)
            except Exception as exc:
                logger.exception("Association job %s failed", job_id)
                await self._update(
                    job_id,
                    status="failed",
                    error=f"Association run failed: {type(exc).__name__}: {exc}",
                )

    async def _update(self, job_id: str, **changes: object) -> None:
        async with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={**changes, "updated_at": _now()},
                deep=True,
            )
            state = self._jobs[job_id].model_dump(mode="json")
        await put_job(job_id, {}, state)

    async def _deliver_callback(self, job_id: str) -> None:
        callback_url = os.environ.get("ASSOCIATION_RESULT_URL", "").strip()
        if not callback_url:
            return
        job = await self.get(job_id)
        if job is None or job.result is None:
            return
        timeout = float(os.environ.get("ASSOCIATION_CALLBACK_TIMEOUT_SECONDS", "10"))
        payload = {
            "event": "association.completed",
            "job_id": job_id,
            "case_id": job.case_id,
            "result": job.result.model_dump(mode="json"),
        }
        attempts = max(1, min(int(os.environ.get("ASSOCIATION_CALLBACK_MAX_ATTEMPTS", "3")), 10))
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        callback_url,
                        json=payload,
                        headers={"X-Request-ID": job_id, "Idempotency-Key": job_id},
                    )
                    response.raise_for_status()
                latest = await self.get(job_id)
                await record_callback_attempt(job_id, None)
                await self._update(job_id, callback_status="delivered", callback_attempts=(latest.callback_attempts if latest else 0) + 1, callback_error=None)
                return
            except Exception as exc:
                latest = await self.get(job_id)
                await record_callback_attempt(job_id, type(exc).__name__)
                await self._update(job_id, callback_attempts=(latest.callback_attempts if latest else 0) + 1, callback_error=type(exc).__name__)
                if attempt + 1 < attempts:
                    await asyncio.sleep(min(2**attempt, 5))
        await self._update(job_id, callback_status="failed")


job_manager = AssociationJobManager()
