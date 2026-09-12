from __future__ import annotations

import pytest

from app.contracts import SharedContractValidator
from app.errors import SynthesisError
from app.handoff import EvolutionHandoff
from app.models import PatternSynthesisResult
from app.service import PatternSynthesisService
from tests.fixtures import FakeSemanticSynthesizer, synthesis_request


@pytest.mark.asyncio
async def test_validated_pattern_builds_shared_evolution_request() -> None:
    request = synthesis_request()
    result = await PatternSynthesisService(FakeSemanticSynthesizer()).synthesize(request)
    payload = EvolutionHandoff().build_request(
        request,
        result,
        system_performance={"precision": 0.81, "window": "24h"},
    )

    SharedContractValidator().evolution_request(payload)
    assert payload["trigger"] == {
        "type": "new_spec_ready",
        "context": {
            "source": "pattern_synthesis",
            "synthesis_id": request.synthesis_id,
        },
    }
    assert payload["current_defense_version"] == {"version": "DV-007"}
    assert payload["pattern_spec"] == result.pattern_spec.model_dump(mode="json")


def test_no_pattern_cannot_be_handed_to_evolution() -> None:
    with pytest.raises(SynthesisError) as caught:
        EvolutionHandoff().build_request(
            synthesis_request(),
            PatternSynthesisResult(status="NO_PATTERN", reason="insufficient"),
            system_performance={},
        )
    assert caught.value.code == "no_pattern_for_evolution"
