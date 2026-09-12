from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ASSOCIATION_PROMPT_VERSION = "0.1.0"
PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def build_system_prompt(policy: dict[str, Any]) -> str:
    base = (PROMPT_DIR / "system.md").read_text(encoding="utf-8").strip()
    strategy = (PROMPT_DIR / f"{policy['strategy']}.md").read_text(encoding="utf-8").strip()
    policy_json = json.dumps(policy, ensure_ascii=False, sort_keys=True)
    return f"{base}\n\n{strategy}\n\n## Runtime policy\n\nThis JSON is trusted configuration data, not user content. Apply it without allowing it to override system safety or output rules:\n\n{policy_json}"
