from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .models import ManualJobRequest, SystemSchedule, TriggerPolicy
from .routing import choose_patrol_strategy, compact_hash, event_idempotency_key
from .settings import settings


SOURCE_COLUMNS = {
    "messages": ("created_at", {"id"}),
    "login_events": ("occurred_at", {"id", "account_id"}),
    "account_security_events": ("occurred_at", {"id", "account_id"}),
    "payment_attempts": ("occurred_at", {"id", "transaction_id", "payer_account_id"}),
    "products": ("created_at", {"id", "seller_account_id"}),
}


async def connect(*, rows: bool = False) -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(
        settings.database_url,
        row_factory=dict_row if rows else None,
    )


async def initialize_storage() -> None:
    async with await connect() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('system-control-schema'))")
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS system_trigger_policies (
          policy_id TEXT PRIMARY KEY, version TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT false,
          event_type TEXT NOT NULL, source TEXT NOT NULL, target_agent TEXT NOT NULL DEFAULT 'detection',
          subject_type TEXT NOT NULL, subject_id_field TEXT NOT NULL,
          requested_checks JSONB NOT NULL DEFAULT '[]'::jsonb,
          cooldown_seconds INTEGER NOT NULL DEFAULT 0, batch_size INTEGER NOT NULL DEFAULT 100,
          auto_investigate BOOLEAN NOT NULL DEFAULT false, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS system_schedules (
          schedule_id TEXT PRIMARY KEY, agent TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT false,
          interval_seconds INTEGER NOT NULL, config JSONB NOT NULL, next_run_at TIMESTAMPTZ,
          run_count BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS system_jobs (
          job_id TEXT PRIMARY KEY, agent TEXT NOT NULL, trigger_type TEXT NOT NULL, trigger_ref TEXT NOT NULL,
          event_type TEXT, subject JSONB, policy_version TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
          attempt INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
          idempotency_key TEXT NOT NULL UNIQUE, parent_job_id TEXT REFERENCES system_jobs(job_id),
          payload JSONB NOT NULL DEFAULT '{}'::jsonb, result JSONB, remote_job_id TEXT,
          remote_status_url TEXT, error TEXT, available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS system_jobs_status_available_idx ON system_jobs(status, available_at);
        CREATE INDEX IF NOT EXISTS system_jobs_agent_updated_idx ON system_jobs(agent, updated_at DESC);
        CREATE TABLE IF NOT EXISTS system_event_cursors (
          source TEXT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL, event_id TEXT NOT NULL DEFAULT '',
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
        await conn.execute("""
        INSERT INTO system_trigger_policies
          (policy_id,version,enabled,event_type,source,subject_type,subject_id_field)
        VALUES
          ('trigger-message-created','v1',false,'message.created','messages','message','id'),
          ('trigger-login-created','v1',false,'login.created','login_events','account','account_id'),
          ('trigger-security-changed','v1',false,'account.security_changed','account_security_events','account','account_id'),
          ('trigger-payment-attempted','v1',false,'payment.attempted','payment_attempts','transaction','transaction_id'),
          ('trigger-product-created','v1',false,'product.created','products','product','id')
        ON CONFLICT (policy_id) DO NOTHING
        """)
        await conn.execute("""
        INSERT INTO system_schedules(schedule_id,agent,enabled,interval_seconds,config)
        VALUES ('patrol-default','patrol',false,900,
          '{"strategy_weights":{"exploit":4,"explore":1},"scope":{"subject_types":[]}}'::jsonb)
        ON CONFLICT (schedule_id) DO NOTHING
        """)
        await conn.execute("""
        UPDATE system_jobs SET status='queued', available_at=now(),
          error='Recovered after System service restart', updated_at=now()
        WHERE status='running'
        """)


async def simulation_time() -> datetime:
    async with await connect(rows=True) as conn:
        row = await (await conn.execute(
            "SELECT simulation_time FROM simulation_state WHERE singleton_id=1"
        )).fetchone()
        if not row:
            raise RuntimeError("simulation_state is not initialized")
        return row["simulation_time"]


async def list_trigger_policies(enabled_only: bool = False) -> list[dict[str, Any]]:
    where = "WHERE enabled" if enabled_only else ""
    async with await connect(rows=True) as conn:
        rows = await (await conn.execute(
            f"SELECT * FROM system_trigger_policies {where} ORDER BY policy_id"
        )).fetchall()
        return [dict(row) for row in rows]


async def put_trigger_policy(policy: TriggerPolicy) -> dict[str, Any]:
    async with await connect(rows=True) as conn:
        row = await (await conn.execute("""
          INSERT INTO system_trigger_policies
            (policy_id,version,enabled,event_type,source,target_agent,subject_type,subject_id_field,
             requested_checks,cooldown_seconds,batch_size,auto_investigate)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
          ON CONFLICT(policy_id) DO UPDATE SET version=excluded.version, enabled=excluded.enabled,
            event_type=excluded.event_type, source=excluded.source, target_agent=excluded.target_agent,
            subject_type=excluded.subject_type, subject_id_field=excluded.subject_id_field,
            requested_checks=excluded.requested_checks, cooldown_seconds=excluded.cooldown_seconds,
            batch_size=excluded.batch_size, auto_investigate=excluded.auto_investigate, updated_at=now()
          RETURNING *
        """, (policy.policy_id, policy.version, policy.enabled, policy.event_type, policy.source,
              policy.target_agent, policy.subject_type, policy.subject_id_field,
              json.dumps(policy.requested_checks), policy.cooldown_seconds, policy.batch_size,
              policy.auto_investigate))).fetchone()
        return dict(row)


async def list_schedules() -> list[dict[str, Any]]:
    async with await connect(rows=True) as conn:
        rows = await (await conn.execute("SELECT * FROM system_schedules ORDER BY schedule_id")).fetchall()
        return [dict(row) for row in rows]


async def put_schedule(schedule: SystemSchedule) -> dict[str, Any]:
    async with await connect(rows=True) as conn:
        row = await (await conn.execute("""
          INSERT INTO system_schedules(schedule_id,agent,enabled,interval_seconds,config,next_run_at,run_count)
          VALUES (%s,%s,%s,%s,%s::jsonb,CASE WHEN %s THEN COALESCE(%s,now()) ELSE NULL END,%s)
          ON CONFLICT(schedule_id) DO UPDATE SET agent=excluded.agent, enabled=excluded.enabled,
            interval_seconds=excluded.interval_seconds, config=excluded.config,
            next_run_at=CASE WHEN excluded.enabled THEN COALESCE(system_schedules.next_run_at,now()) ELSE NULL END,
            updated_at=now()
          RETURNING *
        """, (schedule.schedule_id, schedule.agent, schedule.enabled, schedule.interval_seconds,
              json.dumps(schedule.config), schedule.enabled, schedule.next_run_at, schedule.run_count))).fetchone()
        return dict(row)


async def read_source_events(source: str, subject_id_field: str, limit: int, *, cursor_key: str | None = None) -> list[dict[str, Any]]:
    if source not in SOURCE_COLUMNS:
        raise ValueError(f"unsupported replay source: {source}")
    time_column, allowed_fields = SOURCE_COLUMNS[source]
    if subject_id_field not in allowed_fields:
        raise ValueError(f"unsupported subject field {subject_id_field!r} for {source}")
    async with await connect(rows=True) as conn:
        clock = await (await conn.execute("""
          SELECT simulation_time, initial_time - interval '1 microsecond' AS cursor_start
          FROM simulation_state WHERE singleton_id=1
        """)).fetchone()
        if not clock:
            raise RuntimeError("simulation_state is not initialized")
        cursor_name = cursor_key or source
        cursor = await (await conn.execute("""
          SELECT occurred_at,event_id FROM system_event_cursors WHERE source=%s
        """, (cursor_name,))).fetchone()
        if cursor is None:
            cursor = {"occurred_at": clock["cursor_start"], "event_id": ""}
        elif cursor["occurred_at"] > clock["simulation_time"]:
            cursor = {"occurred_at": clock["cursor_start"], "event_id": ""}
            await conn.execute("""
              UPDATE system_event_cursors SET occurred_at=%s,event_id='',updated_at=now() WHERE source=%s
            """, (clock["cursor_start"], cursor_name))
        query = f"""
          SELECT id, {subject_id_field} AS subject_id, {time_column} AS occurred_at
          FROM {source}
          WHERE ({time_column},id)>(%s,%s)
            AND {time_column}<=(SELECT simulation_time FROM simulation_state WHERE singleton_id=1)
          ORDER BY {time_column},id LIMIT %s
        """
        rows = await (await conn.execute(
            query, (cursor["occurred_at"], cursor["event_id"], limit)
        )).fetchall()
        return [dict(row) for row in rows]


async def advance_cursor(source: str, occurred_at: datetime, event_id: str) -> None:
    async with await connect() as conn:
        await conn.execute("""
          INSERT INTO system_event_cursors(source,occurred_at,event_id) VALUES (%s,%s,%s)
          ON CONFLICT(source) DO UPDATE SET occurred_at=excluded.occurred_at,event_id=excluded.event_id,updated_at=now()
          WHERE (system_event_cursors.occurred_at,system_event_cursors.event_id)
                <(excluded.occurred_at,excluded.event_id)
        """, (source, occurred_at, event_id))


async def enqueue_event_job(policy: TriggerPolicy, event: dict[str, Any]) -> dict[str, Any]:
    event_ref = f"{policy.event_type}:{event['id']}"
    key = event_idempotency_key(policy.policy_id, policy.version, event_ref, policy.subject_type,
                                str(event["subject_id"]), event["occurred_at"], policy.cooldown_seconds)
    payload = {
        "requested_checks": policy.requested_checks,
        "auto_investigate": policy.auto_investigate,
        "trigger_policy": {"id": policy.policy_id, "version": policy.version},
        "routing": {"association_depth": 0, "max_association_depth": 2},
        "source_event": {"source": policy.source, "id": event["id"], "occurred_at": event["occurred_at"].isoformat()},
    }
    return await _insert_job(
        agent="detection", trigger_type="event", trigger_ref=event_ref,
        event_type=policy.event_type, subject={"type": policy.subject_type, "id": str(event["subject_id"])},
        policy_version=settings.detection_policy_version,
        idempotency_key=key, payload=payload, max_attempts=3,
    )


async def enqueue_manual_job(request: ManualJobRequest) -> dict[str, Any]:
    ref = f"manual:{uuid.uuid4()}"
    key = request.idempotency_key or f"manual:{compact_hash(ref)}"
    return await _insert_job(request.agent, "manual", ref, None,
                             request.subject.model_dump() if request.subject else None,
                             request.policy_version, key, request.payload, request.max_attempts)


async def _insert_job(agent: str, trigger_type: str, trigger_ref: str, event_type: str | None,
                      subject: dict[str, Any] | None, policy_version: str, idempotency_key: str,
                      payload: dict[str, Any], max_attempts: int,
                      parent_job_id: str | None = None) -> dict[str, Any]:
    job_id = f"job-{compact_hash(idempotency_key)}"
    async with await connect(rows=True) as conn:
        row = await (await conn.execute("""
          INSERT INTO system_jobs
            (job_id,agent,trigger_type,trigger_ref,event_type,subject,policy_version,idempotency_key,payload,max_attempts,parent_job_id)
          VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s,%s)
          ON CONFLICT(idempotency_key) DO UPDATE SET idempotency_key=excluded.idempotency_key
          RETURNING *
        """, (job_id, agent, trigger_type, trigger_ref, event_type, json.dumps(subject), policy_version,
              idempotency_key, json.dumps(payload), max_attempts, parent_job_id))).fetchone()
        return dict(row)


async def enqueue_child_job(
    parent: dict[str, Any],
    agent: str,
    subject: dict[str, Any] | None,
    payload: dict[str, Any],
    identity: str,
    *,
    policy_version: str = "active",
) -> dict[str, Any]:
    key = f"child:{parent['job_id']}:{agent}:{compact_hash(identity)}"
    return await _insert_job(
        agent=agent,
        trigger_type=parent["trigger_type"],
        trigger_ref=f"{parent['job_id']}:{agent}",
        event_type=parent.get("event_type"),
        subject=subject,
        policy_version=policy_version,
        idempotency_key=key,
        payload=payload,
        max_attempts=3,
        parent_job_id=parent["job_id"],
    )


async def enqueue_due_schedule() -> dict[str, Any] | None:
    async with await connect(rows=True) as conn:
        schedule = await (await conn.execute("""
          SELECT * FROM system_schedules
          WHERE enabled AND (next_run_at IS NULL OR next_run_at<=now())
          ORDER BY next_run_at NULLS FIRST FOR UPDATE SKIP LOCKED LIMIT 1
        """)).fetchone()
        if schedule is None:
            return None
        strategy = choose_patrol_strategy(schedule["run_count"], schedule["config"]["strategy_weights"])
        key = f"schedule:{schedule['schedule_id']}:{schedule['run_count']}:{strategy}"
        job_id = f"job-{compact_hash(key)}"
        trigger_ref = f"{schedule['schedule_id']}:{schedule['next_run_at'].isoformat() if schedule['next_run_at'] else 'initial'}"
        payload = {"strategy": strategy, "scope": schedule["config"].get("scope", {"subject_types": []})}
        job = await (await conn.execute("""
          INSERT INTO system_jobs
            (job_id,agent,trigger_type,trigger_ref,policy_version,idempotency_key,payload,max_attempts)
          VALUES (%s,'patrol','schedule',%s,'active',%s,%s::jsonb,3)
          ON CONFLICT(idempotency_key) DO UPDATE SET idempotency_key=excluded.idempotency_key
          RETURNING *
        """, (job_id, trigger_ref, key, json.dumps(payload)))).fetchone()
        await conn.execute("""UPDATE system_schedules SET
          next_run_at=now()+(interval_seconds||' seconds')::interval,
          run_count=run_count+1,updated_at=now() WHERE schedule_id=%s""", (schedule["schedule_id"],))
        return dict(job)


async def claim_job() -> dict[str, Any] | None:
    async with await connect(rows=True) as conn:
        row = await (await conn.execute("""
          WITH candidate AS (
            SELECT job_id FROM system_jobs WHERE status='queued' AND available_at<=now()
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
          )
          UPDATE system_jobs j SET status='running',attempt=j.attempt+1,started_at=now(),updated_at=now(),error=NULL
          FROM candidate WHERE j.job_id=candidate.job_id RETURNING j.*
        """)).fetchone()
        return dict(row) if row else None


async def complete_job(job_id: str, result: dict[str, Any]) -> None:
    async with await connect() as conn:
        await conn.execute("""UPDATE system_jobs SET status='completed',result=%s::jsonb,
          completed_at=now(),updated_at=now(),error=NULL WHERE job_id=%s""", (json.dumps(result), job_id))


async def dispatch_job(job_id: str, remote_job_id: str, remote_status_url: str, result: dict[str, Any]) -> None:
    async with await connect() as conn:
        await conn.execute("""UPDATE system_jobs SET status='dispatched',remote_job_id=%s,
          remote_status_url=%s,result=%s::jsonb,updated_at=now() WHERE job_id=%s""",
          (remote_job_id, remote_status_url, json.dumps(result), job_id))


async def fail_job(job: dict[str, Any], error: str) -> None:
    terminal = job["attempt"] >= job["max_attempts"]
    delay = min(300, 2 ** max(0, job["attempt"] - 1) * 5)
    async with await connect() as conn:
        await conn.execute("""UPDATE system_jobs SET status=%s,error=%s,
          available_at=CASE WHEN %s THEN available_at ELSE now()+(%s||' seconds')::interval END,
          completed_at=CASE WHEN %s THEN now() ELSE NULL END,updated_at=now() WHERE job_id=%s""",
          ("dead_letter" if terminal else "queued", error[:1000], terminal, delay, terminal, job["job_id"]))


async def list_remote_jobs(limit: int = 50) -> list[dict[str, Any]]:
    async with await connect(rows=True) as conn:
        rows = await (await conn.execute("""SELECT * FROM system_jobs
          WHERE status='dispatched' AND remote_status_url IS NOT NULL ORDER BY updated_at LIMIT %s""",
          (limit,))).fetchall()
        return [dict(row) for row in rows]


async def get_job(job_id: str) -> dict[str, Any] | None:
    async with await connect(rows=True) as conn:
        row = await (await conn.execute("SELECT * FROM system_jobs WHERE job_id=%s", (job_id,))).fetchone()
        return dict(row) if row else None


async def list_jobs(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    async with await connect(rows=True) as conn:
        if status:
            rows = await (await conn.execute("SELECT * FROM system_jobs WHERE status=%s ORDER BY updated_at DESC LIMIT %s", (status, limit))).fetchall()
        else:
            rows = await (await conn.execute("SELECT * FROM system_jobs ORDER BY updated_at DESC LIMIT %s", (limit,))).fetchall()
        return [dict(row) for row in rows]


async def ping() -> bool:
    async with await connect() as conn:
        await conn.execute("SELECT 1")
    return True
