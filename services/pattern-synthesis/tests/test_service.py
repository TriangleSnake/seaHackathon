from __future__ import annotations

from copy import deepcopy

import pytest

from app.errors import SynthesisError
from app.models import PatternSynthesisRequest, SemanticSynthesisOutput
from app.service import PatternSynthesisService
from tests.fixtures import (
    FakeSemanticSynthesizer,
    LITERAL_CUE,
    request_payload,
    reusable_pattern_output,
    synthesis_request,
)


@pytest.mark.asyncio
async def test_multiple_related_cases_emit_one_grounded_pattern() -> None:
    fake = FakeSemanticSynthesizer()
    result = await PatternSynthesisService(fake).synthesize(synthesis_request())

    assert result.status == "PATTERN"
    assert result.pattern_spec is not None
    assert result.pattern_spec.supporting_cases == (
        "CASE-FRAUD-001",
        "CASE-SUSPICIOUS-002",
    )
    assert result.pattern_spec.pattern_id.startswith("PAT-")
    assert fake.contexts[0]["candidate_cases"][0]["verdict"] == "fraud"
    assert "scoreboard" not in fake.contexts[0]["candidate_cases"][0]


@pytest.mark.asyncio
async def test_normal_case_appears_only_as_counterexample() -> None:
    result = await PatternSynthesisService(FakeSemanticSynthesizer()).synthesize(
        synthesis_request()
    )

    assert result.pattern_spec is not None
    assert result.pattern_spec.counterexamples == ("CASE-NORMAL-003",)
    assert "CASE-NORMAL-003" not in result.pattern_spec.supporting_cases
    assert "EVID-MSG-003" not in result.pattern_spec.evidence_refs


@pytest.mark.asyncio
async def test_hallucinated_supporting_case_is_rejected() -> None:
    output = reusable_pattern_output()
    output.pattern.supporting_cases = (  # type: ignore[union-attr]
        "CASE-FRAUD-001",
        "CASE-HALLUCINATED",
    )
    with pytest.raises(SynthesisError, match="supporting_cases") as caught:
        await PatternSynthesisService(FakeSemanticSynthesizer(output)).synthesize(
            synthesis_request()
        )
    assert caught.value.code == "unknown_supporting_case"


@pytest.mark.asyncio
async def test_hallucinated_evidence_ref_is_rejected() -> None:
    output = reusable_pattern_output()
    output.pattern.evidence_refs = (  # type: ignore[union-attr]
        "EVID-MSG-001",
        "EVID-HALLUCINATED",
    )
    with pytest.raises(SynthesisError) as caught:
        await PatternSynthesisService(FakeSemanticSynthesizer(output)).synthesize(
            synthesis_request()
        )
    assert caught.value.code == "unknown_evidence_ref"


@pytest.mark.asyncio
async def test_phrase_only_capability_is_reflected_in_defense_gap() -> None:
    result = await PatternSynthesisService(FakeSemanticSynthesizer()).synthesize(
        synthesis_request()
    )
    assert result.pattern_spec is not None
    assert "flat exact-substring" in result.pattern_spec.current_defense_gap
    assert "role-aware conjunction" in result.pattern_spec.current_defense_gap
    assert result.provenance is not None
    assert result.provenance.defense_capability_refs == (
        "detection-flat-chat-phrases",
    )


@pytest.mark.asyncio
async def test_literal_message_cue_is_preserved_exactly() -> None:
    result = await PatternSynthesisService(FakeSemanticSynthesizer()).synthesize(
        synthesis_request()
    )
    assert result.pattern_spec is not None
    literal = next(
        item for item in result.pattern_spec.observed_signals if item.field == "message.text"
    )
    assert literal.operator == "contains"
    assert literal.value == LITERAL_CUE
    assert result.provenance.signal_grounding[1].grounding_kind == "literal"


@pytest.mark.asyncio
async def test_unsupported_literal_cue_fails_closed() -> None:
    output = reusable_pattern_output()
    output.pattern.observed_signals[1].value = "fabricated phrase"  # type: ignore[union-attr]
    with pytest.raises(SynthesisError) as caught:
        await PatternSynthesisService(FakeSemanticSynthesizer(output)).synthesize(
            synthesis_request()
        )
    assert caught.value.code == "unsupported_literal_signal"


@pytest.mark.asyncio
async def test_no_common_pattern_returns_explicit_no_pattern() -> None:
    semantic = SemanticSynthesisOutput(
        outcome="NO_PATTERN",
        reason="The cases do not share a sufficiently grounded behavior.",
    )
    result = await PatternSynthesisService(
        FakeSemanticSynthesizer(semantic)
    ).synthesize(synthesis_request())
    assert result.status == "NO_PATTERN"
    assert result.pattern_spec is None
    assert "do not share" in result.reason


@pytest.mark.asyncio
async def test_single_case_does_not_automatically_become_pattern() -> None:
    payload = request_payload()
    payload["candidate_results"] = payload["candidate_results"][:1]
    fake = FakeSemanticSynthesizer()
    result = await PatternSynthesisService(fake).synthesize(
        PatternSynthesisRequest.model_validate(payload)
    )
    assert result.status == "NO_PATTERN"
    assert fake.contexts == []


@pytest.mark.asyncio
async def test_pattern_id_is_runtime_owned_and_deterministic() -> None:
    request = synthesis_request()
    first = await PatternSynthesisService(FakeSemanticSynthesizer()).synthesize(request)
    second = await PatternSynthesisService(FakeSemanticSynthesizer()).synthesize(request)
    assert first.pattern_spec.pattern_id == second.pattern_spec.pattern_id  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_active_defense_input_is_not_mutated() -> None:
    class MutatingFake(FakeSemanticSynthesizer):
        async def synthesize(self, context):
            context["active_defense_context"]["capability_summary"]["summary"] = "mutated"
            return SemanticSynthesisOutput(outcome="NO_PATTERN", reason="No pattern")

    request = synthesis_request()
    before = deepcopy(request.model_dump(mode="json"))
    await PatternSynthesisService(MutatingFake()).synthesize(request)
    assert request.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_invalid_shared_investigation_contract_is_rejected_before_llm() -> None:
    payload = request_payload()
    payload["candidate_results"][0]["scoreboard"] = {}
    request = PatternSynthesisRequest.model_validate(payload)
    fake = FakeSemanticSynthesizer()
    with pytest.raises(SynthesisError) as caught:
        await PatternSynthesisService(fake).synthesize(request)
    assert caught.value.code == "invalid_investigation_contract"
    assert fake.contexts == []
