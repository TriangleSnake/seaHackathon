"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.readiness import GatewayReadinessProbe
from app.api.routes import router
from app.settings import Settings


def create_app(
    settings: Optional[Settings] = None,
    readiness_probe: Optional[GatewayReadinessProbe] = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = resolved_settings
        application.state.readiness_probe = readiness_probe or GatewayReadinessProbe(
            resolved_settings.agentgateway_url,
            resolved_settings.gateway_timeout_seconds,
        )
        yield
        await application.state.readiness_probe.close()

    application = FastAPI(
        title="Fraud Investigation Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    application.include_router(router)
    return application


app = create_app()
