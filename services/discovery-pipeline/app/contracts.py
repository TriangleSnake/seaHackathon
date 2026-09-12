from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


class ContractValidationError(ValueError):
    pass


class ContractValidator:
    """Validate payloads against the repository-owned external contracts."""

    _SCHEMAS = (
        "common.schema.json",
        "detection.schema.json",
        "scoreboard.schema.json",
        "patrol.schema.json",
        "association.schema.json",
        "investigation.schema.json",
    )

    def __init__(self, schema_dir: str | Path) -> None:
        self._registry = Registry()
        for name in self._SCHEMAS:
            document = json.loads((Path(schema_dir) / name).read_text(encoding="utf-8"))
            self._registry = self._registry.with_resource(
                document["$id"], Resource.from_contents(document)
            )

    def validate(self, schema_name: str, definition: str, payload: Any) -> None:
        validator = Draft202012Validator(
            {"$ref": f"{schema_name}#/$defs/{definition}"},
            registry=self._registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
        if not errors:
            return
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ContractValidationError(
            f"{schema_name}#/$defs/{definition} rejected {location}: {error.message}"
        )

    def patrol_request(self, payload: Any) -> None:
        self.validate("patrol.schema.json", "PatrolRequest", payload)

    def patrol_result(self, payload: Any) -> None:
        self.validate("patrol.schema.json", "PatrolResult", payload)

    def association_request(self, payload: Any) -> None:
        self.validate("association.schema.json", "AssociationRequest", payload)

    def association_result(self, payload: Any) -> None:
        self.validate("association.schema.json", "AssociationResult", payload)

    def investigation_request(self, payload: Any) -> None:
        self.validate("investigation.schema.json", "InvestigationRequest", payload)

    def investigation_result(self, payload: Any) -> None:
        self.validate("investigation.schema.json", "InvestigationResult", payload)
