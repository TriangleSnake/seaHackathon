"""Shared specialist-agent contract and implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.models import AgentRun, Evidence, Subject, ToolDefinition
from app.gateways.openai import Analyzer, ToolExecutor


class DomainAgent:
    name = "base"
    allowed_tools: tuple[str, ...] = ()
    primary_subject_types: tuple[str, ...] = ()
    item_score_weights: dict[str, float] = {}
    evidence_terms: tuple[str, ...] = ()
    trigger_terms: tuple[str, ...] = ()
    common_evidence_terms: tuple[str, ...] = (
        "account",
        "login",
        "security",
        "device",
        "ip",
        "case",
        "entity",
        "relationship",
        "simulation",
    )

    def __init__(self, analyzer: Analyzer, prompt_path: Path) -> None:
        self._analyzer = analyzer
        self._prompt = prompt_path.read_text(encoding="utf-8")

    @property
    def allowed_tool_names(self) -> tuple[str, ...]:
        return self.allowed_tools

    @staticmethod
    def _has_content(item: Evidence) -> bool:
        if not item.type.startswith("tool_result:"):
            return True
        if item.data.get("found") is False or item.data.get("count") == 0:
            return False
        return True

    def relevance(
        self,
        subject: Subject,
        evidence: list[Evidence],
        trigger_text: str,
    ) -> int:
        searchable = []
        for item in evidence:
            if not self._has_content(item):
                continue
            content = item.type
            if not item.type.startswith("tool_result:"):
                content = f"{content} {item.data}"
            searchable.append(content)
        haystack = " ".join([subject.type, trigger_text] + searchable).lower()
        return sum(haystack.count(term) for term in self.evidence_terms + self.trigger_terms)

    def routing_score(
        self,
        subject: Subject,
        evidence: list[Evidence],
        trigger_text: str,
    ) -> int:
        subject_affinity = 100 if subject.type in self.primary_subject_types else 0
        return subject_affinity + self.relevance(subject, evidence, trigger_text)

    def select_evidence(self, evidence: list[Evidence]) -> list[Evidence]:
        selected = []
        for item in evidence:
            if not self._has_content(item):
                continue
            content = item.type.lower()
            if not item.type.startswith("tool_result:"):
                content = f"{content} {item.data}".lower()
            if item.source == "detection" or any(
                term in content
                for term in self.evidence_terms + self.common_evidence_terms
            ):
                selected.append(item)
        return selected

    async def run(
        self,
        subject: Subject,
        evidence: list[Evidence],
        trigger_text: str,
        max_output_tokens: int,
        gateway_tools: list[ToolDefinition],
        execute_tool: ToolExecutor,
        max_tool_calls: int,
    ) -> AgentRun:
        relevant_evidence = self.select_evidence(evidence)
        specialist_tools = [
            tool for tool in gateway_tools if tool.name in self.allowed_tools
        ]
        context: dict[str, Any] = {
            "subject": subject.model_dump(),
            "detection_context": trigger_text,
            "evidence": [item.model_dump(mode="json") for item in relevant_evidence],
            "allowed_evidence_refs": [item.id for item in relevant_evidence],
            "available_tools": [tool.name for tool in specialist_tools],
            "tool_budget": max_tool_calls,
            "output_language": "Traditional Chinese (zh-TW)",
            # Specialists choose evidence-based scores; deterministic weights stay
            # private to application code so they cannot bias model judgment.
            "score_items": list(self.item_score_weights),
            "score_scale": {
                "0": "strong legitimate evidence",
                "1": "mostly legitimate with little fraud indication",
                "2": "weak fraud indicators",
                "3": "meaningful unresolved fraud indicators",
                "4": "strong fraud evidence",
                "5": (
                    "explicit and decisive fraud evidence; requires "
                    "is_direct_evidence=true"
                ),
            },
            "citation_policy": (
                "IDs present in successful tool outputs become allowed evidence refs."
            ),
        }
        return await self._analyzer.analyze(
            self.name,
            self._prompt,
            context,
            max_output_tokens,
            specialist_tools,
            execute_tool,
            max_tool_calls,
        )
