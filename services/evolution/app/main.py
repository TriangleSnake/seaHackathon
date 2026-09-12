from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
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
        await connection.execute("""CREATE TABLE IF NOT EXISTS evolution_run_events (
          event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES evolution_runs(run_id) ON DELETE CASCADE,
          stage TEXT NOT NULL, component TEXT NOT NULL, status TEXT NOT NULL, summary TEXT,
          details JSONB NOT NULL DEFAULT '{}'::jsonb, started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ)""")
        await connection.execute("""INSERT INTO evolution_run_events
          (event_id,run_id,stage,component,status,summary,started_at,completed_at)
          SELECT 'EVT-' || md5(run_id || ':received'),run_id,'received','evolution','completed',
                 'Run accepted and persisted.',created_at,created_at FROM evolution_runs
          ON CONFLICT (event_id) DO NOTHING""")
        await connection.execute("""UPDATE evolution_run_events
          SET started_at = completed_at
          WHERE component = 'evolution' AND stage = 'received'
            AND completed_at IS NOT NULL AND started_at > completed_at""")

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

class RunEvent(BaseModel):
    event_id: str
    stage: str
    component: str
    status: str
    summary: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    completed_at: datetime | None = None

class EvolutionRunResponse(BaseModel):
    run_id: str
    state: str
    trigger_type: str
    target_policy: str | None = None
    candidate_id: str | None = None
    evaluation_id: str | None = None
    current_stage: str
    progress: int = Field(ge=0, le=100)
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    events: list[RunEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

class DefenseVersionResponse(BaseModel):
    version: str
    status: str
    base_version: str | None = None
    candidate_id: str | None = None
    evaluation_id: str | None = None
    policies: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

STAGE_PROGRESS = {"RECEIVED": 0, "DIAGNOSING": 16, "PROPOSED": 32, "BUILDING": 48,
                  "VALIDATING": 64, "AWAITING_APPROVAL": 80, "APPROVED": 92,
                  "ACTIVE": 100, "REJECTED": 100, "FAILED": 100}

async def run_responses(limit: int) -> list[EvolutionRunResponse]:
    records = await rows("SELECT * FROM evolution_runs ORDER BY updated_at DESC LIMIT %s", (limit,))
    if not records:
        return []
    events = await rows("SELECT * FROM evolution_run_events WHERE run_id = ANY(%s) ORDER BY started_at", ([item["run_id"] for item in records],))
    by_run: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_run.setdefault(event.pop("run_id"), []).append(event)
    return [EvolutionRunResponse(**item, current_stage=item["state"].lower(),
            progress=STAGE_PROGRESS.get(item["state"], 0), error=item["details"].get("error"),
            events=by_run.get(item["run_id"], [])) for item in records]

@app.get("/health")
async def health() -> dict[str, str]: return {"status": "ok", "service": "evolution"}

@app.get("/evolution/runs", response_model=list[EvolutionRunResponse])
async def list_runs(limit: int = Query(50, ge=1, le=200)) -> list[EvolutionRunResponse]:
    return await run_responses(limit)

@app.post("/evolution/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(request: EvolutionRunRequest) -> EvolutionRunResponse:
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
        record = dict(await result.fetchone())
        await connection.execute("""INSERT INTO evolution_run_events
          (event_id,run_id,stage,component,status,summary,completed_at)
          VALUES (%s,%s,'received','evolution','completed','Run accepted and persisted.',now())""",
          (f"EVT-{uuid4()}", run_id))
        return EvolutionRunResponse(**record, current_stage="received", progress=0, events=[])

@app.get("/defense-versions", response_model=list[DefenseVersionResponse])
async def list_defense_versions(limit: int = Query(50, ge=1, le=200)) -> list[DefenseVersionResponse]:
    return await rows("SELECT * FROM defense_versions ORDER BY created_at DESC LIMIT %s", (limit,))
