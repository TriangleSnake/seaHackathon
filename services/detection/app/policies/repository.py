from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import DetectionPolicy


_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PolicyNotFoundError(LookupError):
    pass


class FilePolicyRepository:
    def __init__(self, policy_dir: str | Path) -> None:
        self.policy_dir = Path(policy_dir)
        self._cache: dict[str, DetectionPolicy] = {}

    def resolve(self, version: str) -> DetectionPolicy:
        if version in self._cache:
            return self._cache[version]
        policy = DetectionPolicy.model_validate(self.read_document(version))
        self._cache[version] = policy
        return policy

    def read_document(self, version: str) -> dict[str, Any]:
        """Read an uncoerced policy document for cross-validator boundaries."""

        if not _SAFE_VERSION.fullmatch(version):
            raise PolicyNotFoundError(version)
        path = self.policy_dir / f"{version}.json"
        if not path.is_file():
            raise PolicyNotFoundError(version)
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"Policy file {version!r} must contain a JSON object")
        if document.get("version") != version:
            raise ValueError(
                f"Policy file version {document.get('version')!r} does not match "
                f"{version!r}"
            )
        return document
