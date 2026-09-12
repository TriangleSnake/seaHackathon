"""Evidence ledger, gateway-record ingestion, and citation validation."""

from __future__ import annotations

from typing import Any, Iterable

from app.domain.models import Evidence, Finding


class EvidenceLedger:
    def __init__(self, evidence: Iterable[Evidence] = ()) -> None:
        self._items: dict[str, Evidence] = {}
        for item in evidence:
            self.add(item)

    def add(self, evidence: Evidence) -> bool:
        if evidence.id in self._items:
            return False
        self._items[evidence.id] = evidence
        return True

    def ingest_tool_payload(self, tool_name: str, payload: dict[str, Any]) -> list[Evidence]:
        """Turn every record carrying an `id` into independently citable evidence."""
        added: list[Evidence] = []
        source = "external" if payload.get("provider") == "virustotal" else "environment"

        def walk(value: Any, path: str) -> None:
            if isinstance(value, dict):
                record_id = value.get("id")
                if isinstance(record_id, str) and record_id:
                    item = Evidence(
                        id=record_id,
                        source=source,
                        type=f"{tool_name}:{path or 'record'}",
                        ref_id=record_id,
                        data=value,
                    )
                    if self.add(item):
                        added.append(item)
                for key, nested in value.items():
                    walk(nested, f"{path}.{key}" if path else key)
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    walk(nested, f"{path}[{index}]")

        walk(payload, "")
        return added

    def add_tool_result(
        self,
        evidence_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> Evidence:
        item = Evidence(
            id=evidence_id,
            source="investigation",
            type=f"tool_result:{tool_name}",
            ref_id=tool_name,
            data=payload,
        )
        self.add(item)
        self.ingest_tool_payload(tool_name, payload)
        return item

    def validate_findings(self, findings: Iterable[Finding]) -> tuple[list[Finding], int]:
        valid: list[Finding] = []
        rejected = 0
        known = set(self._items)
        for finding in findings:
            if finding.evidence_refs and set(finding.evidence_refs).issubset(known):
                valid.append(finding)
            else:
                rejected += 1
        return valid, rejected

    def contains(self, evidence_id: str) -> bool:
        return evidence_id in self._items

    def items(self) -> list[Evidence]:
        return list(self._items.values())
