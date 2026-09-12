from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status

from . import storage
from .control import background_tasks, runtime_state
from .models import AgentModelConfig, CaseState, JobState, ManualJobRequest, SystemSchedule, TriggerPolicy


@asynccontextmanager
async def lifespan(_: FastAPI):
    await storage.initialize_storage()
    tasks = background_tasks()
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="System Control Plane", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "degraded" if runtime_state.last_errors else "ok", "loops": runtime_state.last_errors}


@app.get("/ready")
async def ready() -> dict[str, str]:
    try:
        await storage.ping()
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Database unavailable: {type(exc).__name__}") from exc


@app.get("/control/triggers", response_model=list[TriggerPolicy])
async def triggers() -> list[dict[str, Any]]:
    return await storage.list_trigger_policies()


@app.put("/control/triggers/{policy_id}", response_model=TriggerPolicy)
async def update_trigger(policy_id: str, policy: TriggerPolicy) -> dict[str, Any]:
    if policy.policy_id != policy_id:
        raise HTTPException(422, "policy_id does not match path")
    return await storage.put_trigger_policy(policy)


@app.get("/control/schedules", response_model=list[SystemSchedule])
async def schedules() -> list[dict[str, Any]]:
    return await storage.list_schedules()


@app.get("/control/models", response_model=list[AgentModelConfig])
async def models() -> list[dict[str, Any]]:
    return await storage.list_agent_models()


@app.put("/control/models/{component}", response_model=AgentModelConfig)
async def update_model(component: str, config: AgentModelConfig) -> dict[str, Any]:
    if config.component != component:
        raise HTTPException(422, "component does not match path")
    try:
        return await storage.put_agent_model(config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.put("/control/schedules/{schedule_id}", response_model=SystemSchedule)
async def update_schedule(schedule_id: str, schedule: SystemSchedule) -> dict[str, Any]:
    if schedule.schedule_id != schedule_id:
        raise HTTPException(422, "schedule_id does not match path")
    return await storage.put_schedule(schedule)


@app.post("/jobs", response_model=JobState, status_code=status.HTTP_202_ACCEPTED)
async def manual_job(request: ManualJobRequest) -> dict[str, Any]:
    return await storage.enqueue_manual_job(request)


@app.get("/jobs", response_model=list[JobState])
async def jobs(limit: int = Query(50, ge=1, le=200), job_status: str | None = None) -> list[dict[str, Any]]:
    return await storage.list_jobs(limit, job_status)


@app.get("/jobs/{job_id}", response_model=JobState)
async def job(job_id: str) -> dict[str, Any]:
    found = await storage.get_job(job_id)
    if found is None:
        raise HTTPException(404, "System job not found")
    return found


@app.get("/cases", response_model=list[CaseState])
async def cases(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return await storage.list_cases(limit)


@app.get("/cases/{case_id}", response_model=CaseState)
async def case(case_id: str) -> dict[str, Any]:
    found = await storage.get_case(case_id)
    if found is None:
        raise HTTPException(404, "Case not found")
    return found
