from __future__ import annotations

import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Query, status
from pydantic import BaseModel, Field

from .adapters import SharedContractAdapter
from .planner import OpenAIEvolutionPlanner

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://fraud:fraud_dev_password@postgres:5432/fraud_intelligence")
WORKER_POLL_SECONDS = max(1, int(os.environ.get("EVOLUTION_WORKER_POLL_SECONDS", "2")))

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
    worker = asyncio.create_task(worker_loop())
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

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
                  "ACTIVE": 100, "NO_ACTION": 100, "NEEDS_MORE_EVIDENCE": 100,
                  "REJECTED": 100, "FAILED": 100}

def diagnosis_payload(diagnosis: Any) -> dict[str, Any]:
    return {"outcome": diagnosis.outcome.value, "reason": diagnosis.reason,
            "considered_policies": [item.value for item in diagnosis.considered_policies],
            "policy_gaps": [{"policy_type": gap.policy_type.value, "severity": gap.severity.value,
              "confidence": gap.confidence, "symptom": gap.symptom,
              "hypothesized_cause": gap.hypothesized_cause,
              "evidence_refs": list(gap.evidence_refs), "reasoning": gap.reasoning}
              for gap in diagnosis.policy_gaps]}

async def claim_received_run() -> dict[str, Any] | None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as connection:
        async with connection.transaction():
            result = await connection.execute("""SELECT * FROM evolution_runs WHERE state='RECEIVED'
              ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""")
            record = await result.fetchone()
            if record is None: return None
            run = dict(record)
            await connection.execute("UPDATE evolution_runs SET state='DIAGNOSING', updated_at=now() WHERE run_id=%s", (run["run_id"],))
            await connection.execute("""INSERT INTO evolution_run_events
              (event_id,run_id,stage,component,status,summary) VALUES
              (%s,%s,'diagnosing','planner','running','Planner is validating input and diagnosing policy gaps.')""",
              (f"EVT-{uuid4()}", run["run_id"]))
            return run

async def finish_stage(run_id: str, state: str, summary: str, details: dict[str, Any], failed: bool = False) -> None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        await connection.execute("""UPDATE evolution_run_events SET status=%s,summary=%s,details=%s,completed_at=now()
          WHERE event_id=(SELECT event_id FROM evolution_run_events WHERE run_id=%s AND status='running'
          ORDER BY started_at DESC LIMIT 1)""", ("failed" if failed else "completed",summary,Jsonb(details),run_id))
        await connection.execute("UPDATE evolution_runs SET state=%s,details=details || %s,updated_at=now() WHERE run_id=%s",
                                 (state,Jsonb(details),run_id))

def run_planner(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    request = payload.get("request", payload)
    context = SharedContractAdapter().evolution_context(request)
    diagnosis = OpenAIEvolutionPlanner.from_env().diagnose(context)
    serialized = diagnosis_payload(diagnosis)
    outcome = diagnosis.outcome.value
    if outcome == "no_action": return "NO_ACTION", diagnosis.reason, {"diagnosis": serialized}
    if outcome == "needs_more_evidence": return "NEEDS_MORE_EVIDENCE", diagnosis.reason, {"diagnosis": serialized}
    return "PROPOSED", "Planner identified a policy gap; candidate build is ready to dispatch.", {"diagnosis": serialized}

async def process_run(run: dict[str, Any]) -> None:
    try:
        state,summary,details = await asyncio.to_thread(run_planner, run["details"])
        await finish_stage(run["run_id"],state,summary,details)
    except Exception as exc:
        await finish_stage(run["run_id"],"FAILED","Planner could not process this run.",{"error":str(exc)},True)

async def worker_loop() -> None:
    while True:
        try:
            run = await claim_received_run()
            if run is not None:
                await process_run(run)
                continue
        except asyncio.CancelledError: raise
        except Exception: pass
        await asyncio.sleep(WORKER_POLL_SECONDS)

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
