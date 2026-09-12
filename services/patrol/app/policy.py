from __future__ import annotations

import json
import os
from pathlib import Path

from .models import PatrolPolicy


DEFAULT_POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"


def load_active_policy(strategy: str = "exploit") -> PatrolPolicy:
    env_name = f"PATROL_{strategy.upper()}_POLICY_PATH"
    path = Path(os.environ.get(env_name, str(DEFAULT_POLICY_DIR / f"{strategy}.json")))
    policy = PatrolPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    if policy.strategy != strategy:
        raise ValueError(f"Policy strategy {policy.strategy!r} does not match {strategy!r}")
    return policy
