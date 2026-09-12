from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Header, HTTPException, Request, Response, status
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
from app.policies.models import DetectionPolicy
from app.policies.repository import PolicyNotFoundError
from app.errors import CheckUnavailableError, CheckInconclusiveError


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
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
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
    return await _run_detection(payload, request, response, x_request_id)


async def _run_detection(
    payload: DetectionRequest,
    request: Request,
    response: Response,
    x_request_id: str | None,
    policy_override: DetectionPolicy | None = None,
) -> DetectionResult | JSONResponse:
    request_id = x_request_id or request.state.request_id
    try:
        result = await request.app.state.detection_service.detect(payload, policy_override=policy_override)
        response.headers["X-Detection-Policy-Version"] = result.policy_ref.version
        return result
    except (CheckUnavailableError, CheckInconclusiveError) as error:
        return JSONResponse(
            status_code=422,
            content={"error": {
                "code": "check_unavailable" if isinstance(error, CheckUnavailableError) else "check_inconclusive",
                "message": str(error), "request_id": request_id,
            }},
        )
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


@router.get("/policies/detection", tags=["detection-policy"])
async def list_detection_policies(request: Request) -> list[dict]:
    return await request.app.state.policy_repository.list_versions()


@router.post("/policies/detection/validate", tags=["detection-policy"])
async def validate_detection_policy(policy: DetectionPolicy) -> dict[str, object]:
    return {"valid": True, "version": policy.version}


@router.post("/policies/detection/drafts", status_code=status.HTTP_201_CREATED, tags=["detection-policy"])
async def create_detection_policy_draft(
    request: Request,
    policy: DetectionPolicy,
    source: Literal["human", "evolution"] = "human",
) -> dict[str, object]:
    created = await request.app.state.policy_repository.save_draft(policy, source)
    if not created:
        raise HTTPException(status_code=409, detail="Policy version already exists or policy storage is unavailable.")
    return {"created": True, "version": policy.version, "source": source}


@router.post(
    "/policies/detection/test",
    response_model=DetectionResult,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    tags=["detection-policy"],
)
async def test_detection_policy(
    request: Request,
    response: Response,
    policy: DetectionPolicy = Body(),
    detection_request: DetectionRequest = Body(alias="request"),
    x_request_id: Annotated[str | None, Header()] = None,
) -> DetectionResult | JSONResponse:
    return await _run_detection(detection_request, request, response, x_request_id, policy_override=policy)


@router.post("/policies/detection/publish", tags=["detection-policy"])
async def publish_detection_policy(
    request: Request,
    policy: DetectionPolicy,
    source: Literal["human", "evolution"] = "human",
) -> dict[str, object]:
    published = await request.app.state.policy_repository.publish(policy, source)
    if not published:
        raise HTTPException(status_code=409, detail="Version exists with a different immutable policy document or storage is unavailable.")
    return {"published": True, "active_version": policy.version}


@router.post("/policies/detection/rollback/{version}", tags=["detection-policy"])
async def rollback_detection_policy(version: str, request: Request) -> dict[str, object]:
    activated = await request.app.state.policy_repository.activate(version)
    if not activated:
        raise HTTPException(status_code=404, detail="Detection policy version was not found.")
    return {"activated": True, "active_version": version}
