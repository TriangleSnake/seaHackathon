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
from app.policies.repository import PolicyNotFoundError


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
    responses={422: {"model": ErrorResponse}},
    tags=["investigation"],
)
async def investigate(
    payload: InvestigationRequest,
    request: Request,
    response: Response,
    x_request_id: Annotated[Optional[str], Header()] = None,
) -> Union[InvestigationResult, JSONResponse]:
    del response
    request_id = x_request_id or request.state.request_id
    try:
        return await request.app.state.orchestrator.investigate(
            payload,
            request_id,
            request.headers.get("traceparent"),
        )
    except PolicyNotFoundError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "scoreboard_config_not_found",
                    "message": str(exc),
                    "request_id": request_id,
                }
            },
        )
