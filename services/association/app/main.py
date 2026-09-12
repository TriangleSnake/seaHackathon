from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .agent import run_association
from .models import AssociationRequest, AssociationResult
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
