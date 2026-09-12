from __future__ import annotations

from contextlib import asynccontextmanager

from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException, Request, status

from .agent import run_association
from .jobs import job_manager
from .models import (
    AssociationJobAccepted,
    AssociationJobState,
    AssociationPolicy,
    AssociationRequest,
    AssociationResult,
)
from .policy import load_active_policy
from .prompt import ASSOCIATION_PROMPT_VERSION
from .runtime import model_override, reasoning_override
from .storage import initialize_storage
from .policy_store import activate, initialize_policy_storage, list_policies, publish, save_draft


@asynccontextmanager
async def lifespan(_: FastAPI):
    await initialize_storage()
    await initialize_policy_storage()
    for strategy in ("focused", "discovery"):
        if not await list_policies("association", strategy):
            policy = load_active_policy(strategy)
            await publish("association", strategy, policy.version, policy.model_dump(mode="json"), "human")
    yield


app = FastAPI(title="Association Service", version="0.2.0", lifespan=lifespan)


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


@app.get("/association/jobs", response_model=list[AssociationJobState])
async def list_association_jobs(limit: int = 50) -> list[AssociationJobState]:
    return await job_manager.list(limit)


@app.post("/association/jobs/{job_id}/retry-callback", response_model=AssociationJobState)
async def retry_association_callback(job_id: str) -> AssociationJobState:
    job = await job_manager.retry_callback(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Association job not found")
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Association job is not completed")
    return job


@app.get("/policies/association")
async def association_policies(strategy: str | None = None) -> list[dict[str, Any]]:
    return await list_policies("association", strategy)


@app.post("/policies/association/{strategy}/validate")
async def validate_association_policy(strategy: Literal["focused", "discovery"], document: dict[str, Any] = Body(...)) -> dict[str, Any]:
    policy = AssociationPolicy.model_validate(document)
    if policy.strategy != strategy:
        raise HTTPException(422, "Policy strategy mismatch")
    return {"valid": True, "policy": policy.model_dump(mode="json")}


@app.post("/policies/association/{strategy}/test", response_model=AssociationResult)
async def test_association_policy(strategy: Literal["focused", "discovery"], payload: dict[str, Any] = Body(...)) -> AssociationResult:
    policy = AssociationPolicy.model_validate(payload.get("policy"))
    request = AssociationRequest.model_validate(payload.get("request"))
    if policy.strategy != strategy or request.strategy != strategy: raise HTTPException(422, "Strategy mismatch")
    return await run_association(request, policy)


@app.post("/policies/association/{strategy}/drafts", status_code=201)
async def draft_association_policy(strategy: Literal["focused", "discovery"], document: dict[str, Any] = Body(...), source: Literal["human", "evolution"] = "human") -> dict[str, Any]:
    policy = AssociationPolicy.model_validate(document)
    if policy.strategy != strategy: raise HTTPException(422, "Policy strategy mismatch")
    if not await save_draft("association", strategy, policy.version, policy.model_dump(mode="json"), source): raise HTTPException(409, "Policy version already exists")
    return {"draft": True, "strategy": strategy, "version": policy.version}


@app.post("/policies/association/{strategy}/publish")
async def publish_association_policy(strategy: Literal["focused", "discovery"], document: dict[str, Any] = Body(...), source: Literal["human", "evolution"] = "human") -> dict[str, Any]:
    policy = AssociationPolicy.model_validate(document)
    if policy.strategy != strategy: raise HTTPException(422, "Policy strategy mismatch")
    if not await publish("association", strategy, policy.version, policy.model_dump(mode="json"), source):
        raise HTTPException(409, "Policy version already exists; publish a new version")
    return {"published": True, "strategy": strategy, "version": policy.version}


@app.post("/policies/association/{strategy}/rollback/{version}")
async def rollback_association_policy(strategy: Literal["focused", "discovery"], version: str) -> dict[str, Any]:
    if not await activate("association", strategy, version): raise HTTPException(404, "Policy version not found")
    return {"active": True, "strategy": strategy, "version": version}
