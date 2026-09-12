from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_name: str
    database_url: str
    database_pool_size: int
    openai_api_key: str | None
    openai_model: str
    policy_dir: str = "config/policies"
    candidate_policy_dir: str | None = None
    default_policy_version: str = "baseline-v1"

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.environ.get("OPENAI_API_KEY") or None
        return cls(
            service_name=os.environ.get("DETECTION_SERVICE_NAME", "fraud-detection"),
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql://fraud:fraud_dev_password@localhost:5432/fraud_intelligence",
            ),
            database_pool_size=int(os.environ.get("DATABASE_POOL_SIZE", "5")),
            openai_api_key=api_key,
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            policy_dir=os.environ.get("DETECTION_POLICY_DIR", "config/policies"),
            candidate_policy_dir=os.environ.get("DETECTION_CANDIDATE_POLICY_DIR")
            or None,
            default_policy_version=os.environ.get(
                "DEFAULT_DETECTION_POLICY_VERSION", "baseline-v1"
            ),
        )
