from __future__ import annotations

import json
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://fraud:fraud_dev_password@postgres:5432/fraud_intelligence")


async def initialize_storage() -> None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('agent-control-schema'))")
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_jobs (
          job_id TEXT PRIMARY KEY, agent TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed')),
          request JSONB NOT NULL, state JSONB NOT NULL,
          callback_attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS agent_jobs_agent_updated_idx ON agent_jobs(agent, updated_at DESC);
        CREATE TABLE IF NOT EXISTS patrol_schedules (
          strategy TEXT PRIMARY KEY CHECK (strategy IN ('exploit','explore')),
          enabled BOOLEAN NOT NULL DEFAULT false,
          interval_seconds INTEGER NOT NULL CHECK (interval_seconds >= 60),
          scope JSONB NOT NULL DEFAULT '{"subject_types":[]}'::jsonb,
          next_run_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        INSERT INTO patrol_schedules(strategy, enabled, interval_seconds)
          VALUES ('exploit', false, 900), ('explore', false, 86400)
          ON CONFLICT (strategy) DO NOTHING;
        """)
        await conn.execute("""UPDATE agent_jobs SET status='failed',
          state=jsonb_set(jsonb_set(state,'{status}','\"failed\"'::jsonb),'{error}','\"Interrupted by service restart\"'::jsonb),
          updated_at=now() WHERE agent='patrol' AND status IN ('queued','running')""")


async def put_job(job_id: str, request: dict[str, Any], state: dict[str, Any]) -> None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await conn.execute("""INSERT INTO agent_jobs(job_id,agent,status,request,state)
          VALUES (%s,'patrol',%s,%s::jsonb,%s::jsonb)
          ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,state=excluded.state,updated_at=now()""",
          (job_id, state["status"], json.dumps(request), json.dumps(state)))


async def get_job(job_id: str) -> dict[str, Any] | None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row) as conn:
        row = await (await conn.execute("SELECT state FROM agent_jobs WHERE agent='patrol' AND job_id=%s", (job_id,))).fetchone()
        return row["state"] if row else None


async def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row) as conn:
        rows = await (await conn.execute("SELECT state FROM agent_jobs WHERE agent='patrol' ORDER BY updated_at DESC LIMIT %s", (max(1,min(limit,200)),))).fetchall()
        return [row["state"] for row in rows]


async def list_schedules() -> list[dict[str, Any]]:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row) as conn:
        return list(await (await conn.execute("SELECT * FROM patrol_schedules ORDER BY strategy")).fetchall())


async def update_schedule(strategy: str, enabled: bool, interval_seconds: int, scope: dict[str, Any]) -> dict[str, Any]:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row) as conn:
        row = await (await conn.execute("""UPDATE patrol_schedules SET enabled=%s,interval_seconds=%s,scope=%s::jsonb,
          next_run_at=CASE WHEN %s THEN now() ELSE NULL END,updated_at=now() WHERE strategy=%s RETURNING *""",
          (enabled, interval_seconds, json.dumps(scope), enabled, strategy))).fetchone()
        return dict(row)


async def claim_due_schedules() -> list[dict[str, Any]]:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row) as conn:
        rows = await (await conn.execute("""UPDATE patrol_schedules SET next_run_at=now()+(interval_seconds||' seconds')::interval
          WHERE enabled AND (next_run_at IS NULL OR next_run_at<=now()) RETURNING *""")).fetchall()
        return list(rows)
