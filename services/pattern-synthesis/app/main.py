"""FastAPI runtime for Pattern Synthesis."""

from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Header, Request, status
from fastapi.responses import JSONResponse

from .errors import SynthesisError
from .models import (
    ErrorResponse,
    HealthResponse,
    PatternSynthesisRequest,
    PatternSynthesisResult,
    ReadinessResponse,
)
from .service import PatternSynthesisService
from .settings import Settings
from .synthesizer import (
    OpenAISemanticSynthesizer,
    SemanticSynthesizer,
    UnavailableSemanticSynthesizer,
)


def create_app(
    settings: Settings | None = None,
    *,
    synthesizer: SemanticSynthesizer | None = None,
) -> FastAPI:
    resolved = settings or Settings.from_env()
    semantic = synthesizer
    if semantic is None:
        semantic = (
            OpenAISemanticSynthesizer(
                resolved.openai_api_key,
                resolved.openai_model,
                timeout_seconds=resolved.openai_timeout_seconds,
                max_output_tokens=resolved.openai_max_output_tokens,
            )
            if resolved.openai_api_key
            else UnavailableSemanticSynthesizer("OPENAI_API_KEY is not configured")
        )
    service = PatternSynthesisService(semantic)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        yield
        await semantic.close()

    application = FastAPI(title="Pattern Synthesis", version="1.0.0", lifespan=lifespan)
    application.state.settings = resolved
    application.state.semantic_synthesizer = semantic
    application.state.synthesis_service = service

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(
            round((perf_counter() - started) * 1000, 2)
        )
        return response

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service=resolved.service_name)

    @application.get(
        "/ready",
        response_model=ReadinessResponse,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}},
        tags=["operations"],
    )
    async def ready(
        request: Request, x_request_id: str | None = Header(default=None)
    ) -> ReadinessResponse | JSONResponse:
        request_id = x_request_id or request.state.request_id
        if not semantic.available:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": {
                        "code": "synthesizer_unavailable",
                        "message": "OpenAI semantic synthesizer is unavailable.",
                        "request_id": request_id,
                        "issues": [],
                    }
                },
            )
        return ReadinessResponse(status="ready", dependencies={"openai": "ok"})

    @application.post(
        "/synthesize",
        response_model=PatternSynthesisResult,
        responses={
            status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
        },
        tags=["pattern-synthesis"],
    )
    async def synthesize(
        payload: PatternSynthesisRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
    ) -> PatternSynthesisResult | JSONResponse:
        request_id = x_request_id or request.state.request_id
        try:
            return await service.synthesize(payload)
        except SynthesisError as exc:
            response_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.code == "synthesizer_unavailable"
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            return JSONResponse(
                status_code=response_status,
                content={
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "request_id": request_id,
                        "issues": list(exc.issues),
                    }
                },
            )

    return application


app = create_app()
