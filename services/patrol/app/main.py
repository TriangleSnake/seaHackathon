from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from .agent import run_patrol
from .handoff import handoff_to_investigation
from .jobs import job_manager, scheduler_loop
from .models import PatrolJobAccepted, PatrolJobState, PatrolPolicy, PatrolRequest, PatrolResult, PatrolScope
from .policy import load_active_policy
from .policy_store import activate, initialize_policy_storage, list_policies, publish, save_draft
from .prompt import PATROL_PROMPT_VERSION
from .runtime import model_override, reasoning_override
from .storage import initialize_storage, list_schedules, update_schedule


class ScheduleUpdate(BaseModel):
    enabled: bool
    interval_seconds: int = Field(ge=60, le=2_592_000)
    scope: PatrolScope = Field(default_factory=PatrolScope)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await initialize_storage()
    await initialize_policy_storage()
    for strategy in ("exploit", "explore"):
        if not await list_policies("patrol", strategy):
            policy = load_active_policy(strategy)
            await publish("patrol", strategy, policy.version, policy.model_dump(mode="json"), "human")
    scheduler_enabled = os.environ.get("PATROL_SCHEDULER_ENABLED", "false").lower() in {"1", "true", "yes"}
    task = asyncio.create_task(scheduler_loop(job_manager)) if scheduler_enabled else None
    yield
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Patrol Service", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def runtime_model_middleware(request: Request, call_next):
    token = model_override.set(request.headers.get("X-Agent-Model"))
    reasoning_token = reasoning_override.set(request.headers.get("X-Agent-Reasoning-Effort"))
    try:
        return await call_next(request)
    finally:
        model_override.reset(token)
        reasoning_override.reset(reasoning_token)


@app.get("/health")
async def health() -> dict[str, str]:
    exploit_policy = load_active_policy("exploit")
    explore_policy = load_active_policy("explore")
    return {
        "status": "ok",
        "scheduler": "local" if os.environ.get("PATROL_SCHEDULER_ENABLED", "false").lower() in {"1", "true", "yes"} else "system-control-plane",
        "exploit_policy_version": exploit_policy.version,
        "explore_policy_version": explore_policy.version,
        "prompt_version": PATROL_PROMPT_VERSION,
    }


@app.post("/patrol/run", response_model=PatrolResult)
async def patrol_run(request: PatrolRequest) -> PatrolResult:
    policy = load_active_policy(request.strategy)
    try:
        result = await run_patrol(request, policy)
        await handoff_to_investigation(result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Patrol run failed: {exc}") from exc


@app.post("/patrol/jobs", response_model=PatrolJobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_patrol_job(request: PatrolRequest) -> PatrolJobAccepted:
    return await job_manager.submit(request, load_active_policy(request.strategy))


@app.get("/patrol/jobs", response_model=list[PatrolJobState])
async def list_patrol_jobs(limit: int = 50) -> list[PatrolJobState]:
    return await job_manager.list(limit)


@app.get("/patrol/jobs/{job_id}", response_model=PatrolJobState)
async def get_patrol_job(job_id: str) -> PatrolJobState:
    job = await job_manager.get(job_id)
    if job is None: raise HTTPException(404, "Patrol job not found")
    return job


@app.post("/patrol/jobs/{job_id}/retry-handoff", response_model=PatrolJobState)
async def retry_patrol_handoff(job_id: str) -> PatrolJobState:
    job = await job_manager.retry_handoff(job_id)
    if job is None: raise HTTPException(404, "Patrol job not found")
    if job.status != "completed" or job.result is None: raise HTTPException(409, "Patrol job is not completed")
    if not job.result.discoveries: raise HTTPException(409, "Patrol job has no discoveries to hand off")
    return job


@app.get("/patrol/schedules")
async def get_patrol_schedules() -> list[dict[str, Any]]:
    return await list_schedules()


@app.put("/patrol/schedules/{strategy}")
async def put_patrol_schedule(strategy: Literal["exploit", "explore"], update: ScheduleUpdate) -> dict[str, Any]:
    return await update_schedule(strategy, update.enabled, update.interval_seconds, update.scope.model_dump(mode="json"))


@app.get("/policies/patrol")
async def patrol_policies(strategy: str | None = None) -> list[dict[str, Any]]:
    return await list_policies("patrol", strategy)


@app.post("/policies/patrol/{strategy}/validate")
async def validate_patrol_policy(strategy: Literal["exploit", "explore"], document: dict[str, Any] = Body(...)) -> dict[str, Any]:
    policy = PatrolPolicy.model_validate(document)
    if policy.strategy != strategy: raise HTTPException(422, "Policy strategy mismatch")
    return {"valid": True, "policy": policy.model_dump(mode="json")}


@app.post("/policies/patrol/{strategy}/test", response_model=PatrolResult)
async def test_patrol_policy(strategy: Literal["exploit", "explore"], payload: dict[str, Any] = Body(...)) -> PatrolResult:
    policy = PatrolPolicy.model_validate(payload.get("policy"))
    request = PatrolRequest.model_validate(payload.get("request"))
    if policy.strategy != strategy or request.strategy != strategy: raise HTTPException(422, "Strategy mismatch")
    return await run_patrol(request, policy)


@app.post("/policies/patrol/{strategy}/drafts", status_code=201)
async def draft_patrol_policy(strategy: Literal["exploit", "explore"], document: dict[str, Any] = Body(...), source: Literal["human", "evolution"] = "human") -> dict[str, Any]:
    policy = PatrolPolicy.model_validate(document)
    if policy.strategy != strategy: raise HTTPException(422, "Policy strategy mismatch")
    if not await save_draft("patrol", strategy, policy.version, policy.model_dump(mode="json"), source): raise HTTPException(409, "Policy version already exists")
    return {"draft": True, "strategy": strategy, "version": policy.version}


@app.post("/policies/patrol/{strategy}/publish")
async def publish_patrol_policy(strategy: Literal["exploit", "explore"], document: dict[str, Any] = Body(...), source: Literal["human", "evolution"] = "human") -> dict[str, Any]:
    policy = PatrolPolicy.model_validate(document)
    if policy.strategy != strategy: raise HTTPException(422, "Policy strategy mismatch")
    if not await publish("patrol", strategy, policy.version, policy.model_dump(mode="json"), source):
        raise HTTPException(409, "Policy version already exists; publish a new version")
    return {"published": True, "strategy": strategy, "version": policy.version}


@app.post("/policies/patrol/{strategy}/rollback/{version}")
async def rollback_patrol_policy(strategy: Literal["exploit", "explore"], version: str) -> dict[str, Any]:
    if not await activate("patrol", strategy, version): raise HTTPException(404, "Policy version not found")
    return {"active": True, "strategy": strategy, "version": version}
