from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Any
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.routes import router
from app.gateways.openai import OpenAIMessageClassifier
from app.policies.repository import FilePolicyRepository
from app.repository import PostgresDetectionRepository
from app.runtime import model_override, reasoning_override
from app.service import DetectionService
from app.settings import Settings


def create_app(
    settings: Settings | None = None,
    repository: Any | None = None,
    classifier: Any | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_repository = repository or PostgresDetectionRepository(
        resolved_settings.database_url,
        resolved_settings.database_pool_size,
    )
    resolved_classifier = classifier
    if resolved_classifier is None and resolved_settings.openai_api_key:
        resolved_classifier = OpenAIMessageClassifier(
            resolved_settings.openai_api_key,
            resolved_settings.openai_model,
        )

    policy_repository = FilePolicyRepository(
        resolved_settings.policy_dir,
        resolved_settings.database_url if repository is None else None,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await policy_repository.initialize()
        for bundled in ("baseline-v1", "candidate-v1"):
            policy = policy_repository.resolve(bundled)
            if not any(row["version"] == bundled for row in await policy_repository.list_versions()):
                await policy_repository.save_draft(policy, "human")
        yield
        await application.state.repository.close()

    application = FastAPI(
        title="Fraud Detection Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.repository = resolved_repository
    application.state.detection_service = DetectionService(
        resolved_repository,
        resolved_classifier,
        policy_repository=policy_repository,
        default_policy_version=resolved_settings.default_policy_version,
    )
    application.state.policy_repository = policy_repository

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        token = model_override.set(request.headers.get("X-Agent-Model"))
        reasoning_token = reasoning_override.set(request.headers.get("X-Agent-Reasoning-Effort"))
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            model_override.reset(token)
            reasoning_override.reset(reasoning_token)

    application.include_router(router)
    return application


app = create_app()
