from __future__ import annotations

import json
import re
from pathlib import Path

from app.policies.models import DetectionPolicy


_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PolicyNotFoundError(LookupError):
    pass


class FilePolicyRepository:
    def __init__(self, policy_dir: str | Path) -> None:
        self.policy_dir = Path(policy_dir)
        self._cache: dict[str, DetectionPolicy] = {}

    def resolve(self, version: str) -> DetectionPolicy:
        if not _SAFE_VERSION.fullmatch(version):
            raise PolicyNotFoundError(version)
        if version in self._cache:
            return self._cache[version]
        path = self.policy_dir / f"{version}.json"
        if not path.is_file():
            raise PolicyNotFoundError(version)
        policy = DetectionPolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if policy.version != version:
            raise ValueError(f"Policy file version {policy.version!r} does not match {version!r}")
        self._cache[version] = policy
        return policy
