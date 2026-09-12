from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Query, status
from pydantic import BaseModel, Field

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://fraud:fraud_dev_password@postgres:5432/fraud_intelligence")

async def initialize() -> None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        await connection.execute("""CREATE TABLE IF NOT EXISTS evolution_runs (
          run_id TEXT PRIMARY KEY, state TEXT NOT NULL, trigger_type TEXT NOT NULL,
          target_policy TEXT, candidate_id TEXT, evaluation_id TEXT, details JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        await connection.execute("""CREATE TABLE IF NOT EXISTS defense_versions (
          version TEXT PRIMARY KEY, status TEXT NOT NULL, base_version TEXT, candidate_id TEXT,
          evaluation_id TEXT, policies JSONB NOT NULL DEFAULT '[]'::jsonb,
          metrics JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")

async def rows(query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        return [dict(item) for item in await (await connection.execute(query, params)).fetchall()]

@asynccontextmanager
async def lifespan(_: FastAPI):
    await initialize()
    yield

app = FastAPI(title="Fraud Evolution Service", version="0.1.0", lifespan=lifespan)

class EvolutionRunRequest(BaseModel):
    trigger_type: str = Field(min_length=1)
    target_policy: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

@app.get("/health")
async def health() -> dict[str, str]: return {"status": "ok", "service": "evolution"}

@app.get("/evolution/runs")
async def list_runs(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return await rows("SELECT * FROM evolution_runs ORDER BY updated_at DESC LIMIT %s", (limit,))

@app.post("/evolution/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(request: EvolutionRunRequest) -> dict[str, Any]:
    run_id = f"EVO-{uuid4()}"
    async with await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=psycopg.rows.dict_row
    ) as connection:
        result = await connection.execute(
            """INSERT INTO evolution_runs
            (run_id, state, trigger_type, target_policy, details)
            VALUES (%s, 'RECEIVED', %s, %s, %s)
            RETURNING *""",
            (run_id, request.trigger_type, request.target_policy, Jsonb(request.details)),
        )
        return dict(await result.fetchone())

@app.get("/defense-versions")
async def list_defense_versions(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return await rows("SELECT * FROM defense_versions ORDER BY created_at DESC LIMIT %s", (limit,))
