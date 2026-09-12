"""Environment-backed service settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_name: str
    agentgateway_url: str
    gateway_timeout_seconds: float

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
        )
