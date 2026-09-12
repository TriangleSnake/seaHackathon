from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .agent import run_patrol
from .models import PatrolRequest, PatrolResult
from .policy import load_active_policy
from .prompt import PATROL_PROMPT_VERSION


app = FastAPI(title="Patrol Service", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    policy = load_active_policy()
    return {
        "status": "ok",
        "policy_version": policy.version,
        "prompt_version": PATROL_PROMPT_VERSION,
    }


@app.post("/patrol/run", response_model=PatrolResult)
async def patrol_run(request: PatrolRequest) -> PatrolResult:
    policy = load_active_policy()
    try:
        return await run_patrol(request, policy)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Patrol run failed: {exc}") from exc
