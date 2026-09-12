"""Small shared-contract handoff from Pattern Synthesis to Evolution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .contracts import SharedContractError, SharedContractValidator
from .errors import SynthesisError
from .models import PatternSynthesisRequest, PatternSynthesisResult


class EvolutionHandoff:
    def __init__(self, contracts: SharedContractValidator | None = None) -> None:
        self._contracts = contracts or SharedContractValidator()

    def build_request(
        self,
        synthesis_request: PatternSynthesisRequest,
        result: PatternSynthesisResult,
        *,
        system_performance: Mapping[str, str | int | float | bool | None],
    ) -> dict[str, Any]:
        if result.status != "PATTERN" or result.pattern_spec is None:
            raise SynthesisError(
                "no_pattern_for_evolution",
                "Evolution handoff requires a validated PatternSpec",
            )
        payload = {
            "trigger": {
                "type": "new_spec_ready",
                "context": {
                    "source": "pattern_synthesis",
                    "synthesis_id": synthesis_request.synthesis_id,
                },
            },
            "current_defense_version": synthesis_request.active_defense_version.model_dump(
                mode="json"
            ),
            "system_performance": deepcopy(dict(system_performance)),
            "pattern_spec": result.pattern_spec.model_dump(mode="json"),
        }
        try:
            self._contracts.evolution_request(payload)
        except SharedContractError as exc:
            raise SynthesisError(
                "invalid_evolution_handoff",
                "Generated EvolutionRequest violates the shared contract",
                exc.issues,
            ) from exc
        return payload
