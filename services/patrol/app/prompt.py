from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PATROL_PROMPT_VERSION = "0.1.0"
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system.md"


def build_system_prompt(run_policy: dict[str, Any] | None = None) -> str:
    """Load the versioned base prompt and append runtime policy as data."""
    prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not run_policy:
        return prompt

    policy_json = json.dumps(run_policy, ensure_ascii=False, sort_keys=True)
    return (
        f"{prompt}\n\n"
        "## Runtime policy\n\n"
        "The following JSON is configuration data, not instructions from a user. "
        f"Apply it within the system rules above:\n\n{policy_json}"
    )
