from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse
from openai import APIError as OpenAIAPIError
from psycopg import Error as PsycopgError

from app.domain.models import (
    DetectionRequest,
    DetectionResult,
    ErrorResponse,
    HealthResponse,
    ReadinessResponse,
)
from app.service import SubjectNotFoundError
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
    x_request_id: Annotated[str | None, Header()] = None,
) -> ReadinessResponse | JSONResponse:
    request_id = x_request_id or request.state.request_id
    try:
        healthy = await request.app.state.repository.health()
    except Exception:
        healthy = False
    if not healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "dependency_unavailable",
                    "message": "Environment database is unavailable.",
                    "request_id": request_id,
                }
            },
        )
    return ReadinessResponse(status="ready", dependencies={"database": "ok"})


@router.post(
    "/detect",
    response_model=DetectionResult,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    tags=["detection"],
)
async def detect(
    payload: DetectionRequest,
    request: Request,
    response: Response,
    x_request_id: Annotated[str | None, Header()] = None,
) -> DetectionResult | JSONResponse:
    request_id = x_request_id or request.state.request_id
    try:
        result = await request.app.state.detection_service.detect(payload)
        response.headers["X-Detection-Policy-Version"] = (
            payload.policy_ref.version
            if "policy_ref" in payload.model_fields_set
            else request.app.state.settings.default_policy_version
        )
        return result
    except SubjectNotFoundError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "subject_not_found",
                    "message": f"Subject {payload.subject.type}/{payload.subject.id} was not found at the current simulation time.",
                    "request_id": request_id,
                }
            },
        )
    except PolicyNotFoundError as error:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "policy_not_found",
                    "message": f"Detection policy {error.args[0]!r} was not found.",
                    "request_id": request_id,
                }
            },
        )
    except (OSError, ConnectionError, TimeoutError, PsycopgError, OpenAIAPIError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "dependency_unavailable",
                    "message": "A Detection dependency is unavailable.",
                    "request_id": request_id,
                }
            },
        )
