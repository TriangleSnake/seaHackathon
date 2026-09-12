from __future__ import annotations

import json
import os
from pathlib import Path

from .models import PatrolPolicy


DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "policies" / "active.json"


def load_active_policy() -> PatrolPolicy:
    path = Path(os.environ.get("PATROL_POLICY_PATH", str(DEFAULT_POLICY_PATH)))
    return PatrolPolicy.model_validate_json(path.read_text(encoding="utf-8"))
