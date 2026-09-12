"""HTTP routes limited to the existing shared Governance contract."""

from fastapi import APIRouter, Request

from ..domain.models import GovernanceRequest, GovernanceResult


router = APIRouter()


@router.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "governance"}


@router.post(
    "/governance/review",
    response_model=GovernanceResult,
    tags=["governance"],
)
async def review(payload: GovernanceRequest, request: Request) -> GovernanceResult:
    return request.app.state.governance_service.review(payload)
