from __future__ import annotations

from fastapi import FastAPI, HTTPException, status

from .agent import run_association
from .jobs import job_manager
from .models import (
    AssociationJobAccepted,
    AssociationJobState,
    AssociationRequest,
    AssociationResult,
)
from .policy import load_active_policy
from .prompt import ASSOCIATION_PROMPT_VERSION


app = FastAPI(title="Association Service", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    focused = load_active_policy("focused")
    discovery = load_active_policy("discovery")
    return {"status": "ok", "focused_policy_version": focused.version, "discovery_policy_version": discovery.version, "prompt_version": ASSOCIATION_PROMPT_VERSION}


@app.post("/associate", response_model=AssociationResult)
async def associate(request: AssociationRequest) -> AssociationResult:
    policy = load_active_policy(request.strategy)
    try:
        return await run_association(request, policy)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Association run failed: {exc}") from exc


@app.post(
    "/association/jobs",
    response_model=AssociationJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_association_job(request: AssociationRequest) -> AssociationJobAccepted:
    policy = load_active_policy(request.strategy)
    return await job_manager.submit(request, policy)


@app.get("/association/jobs/{job_id}", response_model=AssociationJobState)
async def get_association_job(job_id: str) -> AssociationJobState:
    job = await job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Association job not found")
    return job
