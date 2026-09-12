"""Governance FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router
from app.service import GovernanceService


def create_app(service: GovernanceService | None = None) -> FastAPI:
    application = FastAPI(title="Fraud Governance Service", version="0.1.0")
    application.state.governance_service = service or GovernanceService()
    application.include_router(router)
    return application


app = create_app()
