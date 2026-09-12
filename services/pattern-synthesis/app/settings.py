"""Environment-only Pattern Synthesis configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    service_name: str = "fraud-pattern-synthesis"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    openai_timeout_seconds: float = 30
    openai_max_output_tokens: int = 3000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            service_name=os.environ.get(
                "PATTERN_SYNTHESIS_SERVICE_NAME", "fraud-pattern-synthesis"
            ),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_model=os.environ.get(
                "PATTERN_SYNTHESIS_OPENAI_MODEL",
                os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
            ),
            openai_timeout_seconds=float(
                os.environ.get("OPENAI_TIMEOUT_SECONDS", "30")
            ),
            openai_max_output_tokens=int(
                os.environ.get("PATTERN_SYNTHESIS_MAX_OUTPUT_TOKENS", "3000")
            ),
        )
