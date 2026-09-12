"""Application service joining semantic synthesis to deterministic validation."""

from __future__ import annotations

from .models import PatternSynthesisRequest, PatternSynthesisResult
from .synthesizer import SemanticSynthesizer
from .validation import PatternValidator


class PatternSynthesisService:
    def __init__(
        self,
        synthesizer: SemanticSynthesizer,
        validator: PatternValidator | None = None,
    ) -> None:
        self.synthesizer = synthesizer
        self.validator = validator or PatternValidator()

    async def synthesize(
        self, request: PatternSynthesisRequest
    ) -> PatternSynthesisResult:
        self.validator.validate_investigations(request)
        if len(request.candidate_results) < 2:
            return PatternSynthesisResult(
                status="NO_PATTERN",
                reason=(
                    "Insufficient evidence: reusable synthesis requires at least two "
                    "suspicious/fraud InvestigationResults."
                ),
            )
        semantic = await self.synthesizer.synthesize(request.semantic_context())
        if semantic.outcome == "NO_PATTERN":
            return PatternSynthesisResult(status="NO_PATTERN", reason=semantic.reason)
        assert semantic.pattern is not None
        pattern, provenance = self.validator.validate(semantic.pattern, request)
        return PatternSynthesisResult(
            status="PATTERN",
            reason=semantic.reason,
            pattern_spec=pattern,
            provenance=provenance,
        )
