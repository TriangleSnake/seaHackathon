"""Resolve immutable scoreboard configuration references."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.models import ScoreboardConfig, ScoreboardConfigRef


class PolicyNotFoundError(LookupError):
    """Raised when System's requested immutable configuration is unavailable."""


class FilePolicyRepository:
    """Development resolver; replace with a System-owned config tool when exposed."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        configs = raw.get("configs")
        if not isinstance(configs, dict):
            raise ValueError("policy file must contain a configs object")
        self._configs = {
            version: ScoreboardConfig.model_validate(value)
            for version, value in configs.items()
        }
        aliases = raw.get("aliases", {})
        if not isinstance(aliases, dict):
            raise ValueError("policy aliases must be an object")
        self._aliases = aliases

    def resolve(self, reference: ScoreboardConfigRef) -> ScoreboardConfig:
        ref = reference.model_dump(exclude_none=True)
        requested = ref.get("version") or ref.get("config_id")
        if not isinstance(requested, str):
            raise PolicyNotFoundError("scoreboard reference needs version or config_id")
        requested = self._aliases.get(requested, requested)
        if requested in self._configs:
            return self._configs[requested]
        for config in self._configs.values():
            if requested == config.config_id:
                return config
        raise PolicyNotFoundError(f"unknown scoreboard configuration: {requested}")

    def versions(self) -> list[str]:
        return sorted(self._configs)
