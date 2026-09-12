from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PATROL_PROMPT_VERSION = "0.2.0"
_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def build_system_prompt(run_policy: dict[str, Any]) -> str:
    """Load the versioned base prompt and append runtime policy as data."""
    strategy = run_policy["strategy"]
    base = (_PROMPT_DIR / "system.md").read_text(encoding="utf-8").strip()
    strategy_prompt = (_PROMPT_DIR / f"{strategy}.md").read_text(encoding="utf-8").strip()
    policy_json = json.dumps(run_policy, ensure_ascii=False, sort_keys=True)
    return (
        f"{base}\n\n{strategy_prompt}\n\n"
        "## Runtime policy\n\n"
        "The following JSON is the active Patrol Policy and is configuration "
        "data, not instructions from a user. "
        f"Apply it within the system rules above:\n\n{policy_json}"
    )
