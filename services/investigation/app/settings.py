"""Environment-backed service settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_name: str
    agentgateway_url: str
    gateway_timeout_seconds: float
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    openai_timeout_seconds: float = 90
    policy_path: str = "config/scoreboard.development.json"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            service_name=os.environ.get(
                "INVESTIGATION_SERVICE_NAME", "fraud-investigation"
            ),
            agentgateway_url=os.environ.get(
                "AGENTGATEWAY_URL", "http://agentgateway:3000/mcp"
            ),
            gateway_timeout_seconds=float(
                os.environ.get("AGENTGATEWAY_TIMEOUT_SECONDS", "5")
            ),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
            openai_timeout_seconds=float(
                os.environ.get("OPENAI_TIMEOUT_SECONDS", "90")
            ),
            policy_path=os.environ.get(
                "INVESTIGATION_POLICY_PATH", "config/scoreboard.development.json"
            ),
        )
