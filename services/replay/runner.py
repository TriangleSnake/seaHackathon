"""Replay timestamped Environment rows through Detection with durable retries."""
import argparse
import json
import os
import time
from datetime import timedelta

import httpx
import psycopg
from psycopg.types.json import Jsonb

# Fixed, trusted table/column names; never interpolated from user input.
SOURCES = [
    ("accounts", "created_at", "account", "id"),
    ("shops", "created_at", "shop", "id"),
    ("products", "created_at", "product", "id"),
    ("products", "created_at", "account", "seller_account_id"),
    ("transactions", "created_at", "transaction", "id"),
    ("messages", "created_at", "message", "id"),
    ("messages", "created_at", "account", "sender_account_id"),
    ("product_images", "created_at", "product", "product_id"),
    ("message_attachments", "created_at", "message", "message_id"),
    ("reviews", "created_at", "product", "product_id"),
    ("report_records", "created_at", "account", "target_account_id"),
    ("refunds", "requested_at", "transaction", "transaction_id"),
    ("disputes", "created_at", "transaction", "transaction_id"),
    ("disputes", "created_at", "account", "opened_by_account_id"),
] + [(table, "occurred_at", kind, column) for table, kind, column in [
    ("account_status_events", "account", "account_id"),
    ("login_events", "account", "account_id"),
    ("account_security_events", "account", "account_id"),
    ("product_price_events", "product", "product_id"),
    ("product_status_events", "product", "product_id"),
    ("transaction_status_events", "transaction", "transaction_id"),
    ("payment_attempts", "transaction", "transaction_id"),
    ("delivery_events", "transaction", "transaction_id"),
]]

DDL = """
CREATE SCHEMA IF NOT EXISTS replay;
CREATE TABLE IF NOT EXISTS replay.batches (
 id BIGSERIAL PRIMARY KEY, start_time TIMESTAMPTZ NOT NULL,
 end_time TIMESTAMPTZ NOT NULL, policy TEXT NOT NULL,
 complete BOOLEAN NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS replay.jobs (
 batch_id BIGINT REFERENCES replay.batches(id), kind TEXT NOT NULL,
 subject_id TEXT NOT NULL, result JSONB,
 PRIMARY KEY(batch_id, kind, subject_id)
);
"""


def prepare(db, seconds, policy):
    """Atomically persist subjects and publish the next visible time."""
    with db.transaction():
        current, = db.execute(
            "SELECT simulation_time FROM simulation_state WHERE singleton_id=1 FOR UPDATE"
        ).fetchone()
        pending = db.execute(
            "SELECT id, end_time, policy FROM replay.batches WHERE NOT complete ORDER BY id LIMIT 1"
        ).fetchone()
        if pending:
            if pending[1] != current:
                raise RuntimeError("Simulation clock changed during pending replay; restore batch end_time before retry")
            return pending
        previous = db.execute("SELECT end_time FROM replay.batches ORDER BY id DESC LIMIT 1").fetchone()
        if previous and previous[0] != current:
            raise RuntimeError("Simulation clock changed outside replay; use a fresh replay database for a new timeline")
        end = current + timedelta(seconds=seconds)
        batch, = db.execute(
            "INSERT INTO replay.batches(start_time,end_time,policy) VALUES(%s,%s,%s) RETURNING id",
            (current, end, policy),
        ).fetchone()
        for table, stamp, kind, column in SOURCES:
            db.execute(
                f"INSERT INTO replay.jobs(batch_id,kind,subject_id) SELECT %s,%s,{column} "
                f"FROM {table} WHERE {stamp}>%s AND {stamp}<=%s ON CONFLICT DO NOTHING",
                (batch, kind, current, end),
            )
        db.execute("SELECT set_simulation_time(%s)", (end,))
        return batch, end, policy


def dispatch(db, client, batch, end, policy):
    jobs = db.execute(
        "SELECT kind,subject_id FROM replay.jobs WHERE batch_id=%s AND result IS NULL ORDER BY kind,subject_id",
        (batch,),
    ).fetchall()
    for kind, subject_id in jobs:
        # Readers can access the published time, while external clock writers wait.
        with db.transaction():
            current, = db.execute(
                "SELECT simulation_time FROM simulation_state WHERE singleton_id=1 FOR SHARE"
            ).fetchone()
            if current != end:
                raise RuntimeError("Simulation clock drift detected")
            response = client.post("/detect", json={
                "subject": {"type": kind, "id": subject_id},
                "policy_ref": {"type": "detection", "version": policy},
                "trigger_context": {"source": "scheduled", "reason": f"replay:{batch}"},
            })
            response.raise_for_status()
            result = response.json()
            if response.headers.get("X-Detection-Policy-Version") != policy:
                raise RuntimeError("Detection returned an unexpected policy version")
            if result.get("subject") != {"type": kind, "id": subject_id} or not isinstance(result.get("detected"), bool) or not isinstance(result.get("triggers"), list):
                raise RuntimeError("Invalid DetectionResult")
            db.execute("UPDATE replay.jobs SET result=%s WHERE batch_id=%s AND kind=%s AND subject_id=%s",
                       (Jsonb(result), batch, kind, subject_id))
            print(json.dumps({"batch": batch, "subject": subject_id, "detected": result["detected"]}), flush=True)
    db.execute("UPDATE replay.batches SET complete=true WHERE id=%s", (batch,))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Complete one batch, then exit")
    parser.add_argument("--step-seconds", type=int, default=int(os.getenv("REPLAY_STEP_SECONDS", "300")))
    parser.add_argument("--interval-seconds", type=float, default=float(os.getenv("REPLAY_INTERVAL_SECONDS", "5")))
    args = parser.parse_args()
    if args.step_seconds <= 0 or args.interval_seconds <= 0:
        parser.error("step and interval must be positive")
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        locked, = db.execute("SELECT pg_try_advisory_lock(7263419)").fetchone()
        if not locked:
            raise RuntimeError("Another replay runner is already active")
        db.execute(DDL)
        with httpx.Client(base_url=os.getenv("DETECTION_URL", "http://detection:8000"), timeout=60) as client:
            while True:
                batch = prepare(db, args.step_seconds, os.getenv("REPLAY_POLICY_VERSION", "baseline-v1"))
                dispatch(db, client, *batch)
                print(f"Completed batch {batch[0]} at {batch[1]}", flush=True)
                if args.once:
                    return
                time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
