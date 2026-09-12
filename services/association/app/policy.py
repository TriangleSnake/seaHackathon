from __future__ import annotations

import os
from pathlib import Path

from .models import AssociationPolicy
from .policy_store import get_active


DEFAULT_POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"


def load_active_policy(strategy: str) -> AssociationPolicy:
    stored = get_active("association", strategy)
    if stored is not None:
        return AssociationPolicy.model_validate(stored)
    env_name = f"ASSOCIATION_{strategy.upper()}_POLICY_PATH"
    path = Path(os.environ.get(env_name, str(DEFAULT_POLICY_DIR / f"{strategy}.json")))
    policy = AssociationPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    if policy.strategy != strategy:
        raise ValueError(f"Policy strategy {policy.strategy!r} does not match {strategy!r}")
    return policy
