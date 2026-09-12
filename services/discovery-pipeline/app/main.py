from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, Header, Request

from .clients import PipelineClients
from .models import PatrolRequest, UpstreamPipelineResult
from .orchestrator import DiscoveryPipelineOrchestrator
from .settings import Settings


def create_app(
    settings: Settings | None = None,
    orchestrator: DiscoveryPipelineOrchestrator | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned = orchestrator is None
        application.state.orchestrator = orchestrator or DiscoveryPipelineOrchestrator(
            PipelineClients.build(resolved_settings), resolved_settings
        )
        yield
        if owned:
            await application.state.orchestrator.close()

    application = FastAPI(
        title="Upstream Discovery Pipeline",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "discovery-pipeline"}

    @application.post("/pipeline/run", response_model=UpstreamPipelineResult)
    async def run_pipeline(
        payload: PatrolRequest,
        request: Request,
        x_request_id: Annotated[str | None, Header()] = None,
    ) -> UpstreamPipelineResult:
        return await request.app.state.orchestrator.run(
            payload,
            request_id=x_request_id,
            traceparent=request.headers.get("traceparent"),
        )

    return application


app = create_app()
