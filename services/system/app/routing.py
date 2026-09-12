from __future__ import annotations

from datetime import datetime
from hashlib import sha256


def compact_hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()[:24]


def event_idempotency_key(
    policy_id: str,
    version: str,
    event_ref: str,
    subject_type: str,
    subject_id: str,
    occurred_at: datetime,
    cooldown_seconds: int,
) -> str:
    if cooldown_seconds:
        bucket = int(occurred_at.timestamp()) // cooldown_seconds
        identity = f"{policy_id}:{version}:{subject_type}:{subject_id}:cooldown:{bucket}"
    else:
        identity = f"{policy_id}:{version}:{event_ref}"
    return f"event:{compact_hash(identity)}"


def choose_patrol_strategy(run_count: int, weights: dict[str, int]) -> str:
    sequence = [name for name in ("exploit", "explore") for _ in range(weights.get(name, 0))]
    if not sequence:
        raise ValueError("at least one patrol strategy weight must be positive")
    return sequence[run_count % len(sequence)]
