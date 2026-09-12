"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from time import perf_counter
from typing import AsyncIterator, Optional
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.readiness import GatewayReadinessProbe
from app.api.routes import router
from app.agents import ChatAgent, MarketplaceInfoAgent, OrchestratorAgent, OrderAgent
from app.core.orchestrator import InvestigationOrchestrator
from app.gateways.mcp import MCPGatewayClient
from app.gateways.openai import OpenAIAnalyzer, UnavailableAnalyzer
from app.policies.repository import FilePolicyRepository
from app.runtime import model_override, reasoning_override
from app.settings import Settings


logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)


def create_app(
    settings: Optional[Settings] = None,
    readiness_probe: Optional[GatewayReadinessProbe] = None,
    orchestrator: Optional[InvestigationOrchestrator] = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = resolved_settings
        application.state.readiness_probe = readiness_probe or GatewayReadinessProbe(
            resolved_settings.agentgateway_url,
            resolved_settings.gateway_timeout_seconds,
        )
        owned_gateway = None
        owned_analyzer = None
        if orchestrator is not None:
            application.state.orchestrator = orchestrator
        else:
            owned_gateway = MCPGatewayClient(
                resolved_settings.agentgateway_url,
                resolved_settings.gateway_timeout_seconds,
            )
            if resolved_settings.openai_api_key:
                owned_analyzer = OpenAIAnalyzer(
                    resolved_settings.openai_api_key,
                    resolved_settings.openai_model,
                    resolved_settings.openai_timeout_seconds,
                )
            else:
                owned_analyzer = UnavailableAnalyzer("OPENAI_API_KEY is not configured")
            prompts = Path(__file__).resolve().parent / "prompts"
            agents = [
                OrderAgent(owned_analyzer, prompts / "order.md"),
                ChatAgent(owned_analyzer, prompts / "chat.md"),
                MarketplaceInfoAgent(owned_analyzer, prompts / "marketplace_info.md"),
            ]
            orchestrator_agent = OrchestratorAgent(
                owned_analyzer, prompts / "orchestrator.md"
            )
            application.state.orchestrator = InvestigationOrchestrator(
                owned_gateway,
                FilePolicyRepository(resolved_settings.policy_path),
                agents,
                orchestrator_agent=orchestrator_agent,
            )
        yield
        await application.state.readiness_probe.close()
        if owned_gateway is not None:
            await owned_gateway.close()
        if owned_analyzer is not None:
            await owned_analyzer.close()

    application = FastAPI(
        title="Fraud Investigation Service",
        version="0.2.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        token = model_override.set(request.headers.get("X-Agent-Model"))
        reasoning_token = reasoning_override.set(request.headers.get("X-Agent-Reasoning-Effort"))
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                json.dumps(
                    {
                        "event": "http_request_failed",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                    }
                )
            )
            raise
        finally:
            model_override.reset(token)
            reasoning_override.reset(reasoning_token)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                {
                    "event": "http_request_completed",
                    "request_id": request_id,
                    "traceparent": request.headers.get("traceparent"),
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                }
            )
        )
        return response

    application.include_router(router)
    return application


app = create_app()
