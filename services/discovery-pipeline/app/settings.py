from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    patrol_url: str
    association_url: str
    investigation_url: str
    timeout_seconds: float
    scoreboard_config_version: str
    schema_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        schema_default = Path(__file__).resolve().parents[3] / "shared" / "schemas"
        timeout = float(os.environ.get("DISCOVERY_PIPELINE_TIMEOUT_SECONDS", "30"))
        if timeout <= 0:
            raise ValueError("DISCOVERY_PIPELINE_TIMEOUT_SECONDS must be positive")
        return cls(
            patrol_url=os.environ.get("PATROL_URL", "http://patrol:10003").rstrip("/"),
            association_url=os.environ.get(
                "ASSOCIATION_URL", "http://association:10004"
            ).rstrip("/"),
            investigation_url=os.environ.get(
                "INVESTIGATION_URL", "http://investigation:8000"
            ).rstrip("/"),
            timeout_seconds=timeout,
            scoreboard_config_version=os.environ.get(
                "SCOREBOARD_CONFIG_VERSION", "development-v1"
            ),
            schema_dir=Path(
                os.environ.get("DISCOVERY_PIPELINE_SCHEMA_DIR", str(schema_default))
            ),
        )
