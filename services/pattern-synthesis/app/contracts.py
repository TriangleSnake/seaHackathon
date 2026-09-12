"""Validation against immutable repository-owned shared JSON Schemas."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


def _default_schema_root() -> Path:
    configured = os.environ.get("SHARED_SCHEMA_DIR")
    resolved = Path(__file__).resolve()
    repository_schema_root = (
        resolved.parents[3] / "shared" / "schemas"
        if len(resolved.parents) > 3
        else None
    )
    candidates = [
        Path(configured) if configured else None,
        repository_schema_root,
        Path("/shared/schemas"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "Shared schemas not found; set SHARED_SCHEMA_DIR for this runtime layout"
    )


DEFAULT_SCHEMA_ROOT = _default_schema_root()


class SharedContractError(ValueError):
    def __init__(self, contract: str, issues: list[str]) -> None:
        super().__init__(f"{contract} contract validation failed")
        self.contract = contract
        self.issues = tuple(issues)


class SharedContractValidator:
    def __init__(self, schema_root: Path = DEFAULT_SCHEMA_ROOT) -> None:
        self._registry = Registry()
        for schema_path in sorted(schema_root.glob("*.schema.json")):
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self._registry = self._registry.with_resource(
                schema["$id"], Resource.from_contents(schema)
            )

    def validate(
        self, schema_ref: str, payload: Mapping[str, Any], contract: str
    ) -> None:
        validator = Draft202012Validator(
            {"$ref": schema_ref},
            registry=self._registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(dict(payload)),
            key=lambda item: tuple(str(part) for part in item.path),
        )
        if not errors:
            return
        issues = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            issues.append(f"{location}: {error.message}")
        raise SharedContractError(contract, issues)

    def investigation_result(self, payload: Mapping[str, Any]) -> None:
        self.validate(
            "investigation.schema.json#/$defs/InvestigationResult",
            payload,
            "InvestigationResult",
        )

    def pattern_spec(self, payload: Mapping[str, Any]) -> None:
        self.validate(
            "pattern.schema.json#/$defs/PatternSpec", payload, "PatternSpec"
        )

    def evolution_request(self, payload: Mapping[str, Any]) -> None:
        self.validate(
            "evolution.schema.json#/$defs/EvolutionRequest",
            payload,
            "EvolutionRequest",
        )
