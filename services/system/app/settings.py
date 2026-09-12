from __future__ import annotations

import os
from dataclasses import dataclass


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(os.environ.get(name, str(default))), maximum))


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://fraud:fraud_dev_password@postgres:5432/fraud_intelligence",
    )
    detection_url: str = os.environ.get("DETECTION_URL", "http://detection:8000").rstrip("/")
    patrol_url: str = os.environ.get("PATROL_URL", "http://patrol:10003").rstrip("/")
    investigation_url: str = os.environ.get(
        "INVESTIGATION_URL", "http://investigation:8000"
    ).rstrip("/")
    association_url: str = os.environ.get(
        "ASSOCIATION_URL", "http://association:10004"
    ).rstrip("/")
    detection_policy_version: str = os.environ.get(
        "DEFAULT_DETECTION_POLICY_VERSION", "baseline-v1"
    )
    scoreboard_config_version: str = os.environ.get(
        "SCOREBOARD_CONFIG_VERSION", "development-v1"
    )
    event_poll_seconds: int = _integer("SYSTEM_EVENT_POLL_SECONDS", 5, 1, 300)
    schedule_poll_seconds: int = _integer("SYSTEM_SCHEDULE_POLL_SECONDS", 5, 1, 300)
    worker_poll_seconds: int = _integer("SYSTEM_WORKER_POLL_SECONDS", 2, 1, 60)
    remote_poll_seconds: int = _integer("SYSTEM_REMOTE_POLL_SECONDS", 5, 1, 300)
    request_timeout_seconds: int = _integer("SYSTEM_REQUEST_TIMEOUT_SECONDS", 30, 1, 300)
    investigation_timeout_seconds: int = _integer(
        "SYSTEM_INVESTIGATION_TIMEOUT_SECONDS", 180, 1, 600
    )
    max_concurrency: int = _integer("SYSTEM_MAX_CONCURRENCY", 4, 1, 32)


settings = Settings()
