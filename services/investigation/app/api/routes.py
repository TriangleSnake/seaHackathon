"""Investigation HTTP routes."""

from __future__ import annotations

from typing import Annotated, Optional, Union

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.readiness import ReadinessError
from app.domain.models import (
    ErrorResponse,
    HealthResponse,
    InvestigationRequest,
    InvestigationResult,
    ReadinessResponse,
)


router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["operations"])
async def health(request: Request) -> HealthResponse:
    return HealthResponse(status="ok", service=request.app.state.settings.service_name)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}},
    tags=["operations"],
)
async def ready(
    request: Request,
    x_request_id: Annotated[Optional[str], Header()] = None,
) -> Union[ReadinessResponse, JSONResponse]:
    request_id = x_request_id or request.state.request_id
    try:
        await request.app.state.readiness_probe.check(request_id)
    except ReadinessError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "dependency_unavailable",
                    "message": "Agent Gateway or database is unavailable.",
                    "request_id": request_id,
                }
            },
        )
    return ReadinessResponse(status="ready", dependencies={"agentgateway": "ok", "database": "ok"})


@router.post(
    "/investigate",
    response_model=InvestigationResult,
    tags=["investigation"],
)
async def investigate(
    payload: InvestigationRequest,
    request: Request,
    response: Response,
    x_request_id: Annotated[Optional[str], Header()] = None,
) -> InvestigationResult:
    del request, x_request_id
    response.headers["X-Investigation-Placeholder"] = "true"
    return InvestigationResult(
        case_id=payload.case_id,
        subject=payload.detection_result.subject,
        verdict="unknown",
        confidence=0,
        summary=(
            "Placeholder response: the Investigation API contract is available, "
            "but no agents or scoring rules have run."
        ),
        findings=[],
        evidence=payload.detection_result.evidence + payload.existing_evidence,
        agents_invoked=[],
        scoreboard={
            "placeholder": True,
            "status": "not_started",
            "config_ref": payload.scoreboard_config_ref.model_dump(),
        },
        stop_reason="insufficient_evidence",
    )
