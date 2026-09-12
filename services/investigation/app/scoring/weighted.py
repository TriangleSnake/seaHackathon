"""Evidence-bound weighted aggregation for specialist item scores."""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.models import (
    AgentAnalysis,
    AgentScoreAggregate,
    SpecialistAgentResult,
    WeightedItemContribution,
)


class AgentScoreAggregator:
    """Validate raw item scores and calculate deterministic weighted averages."""

    def aggregate(
        self,
        agent: str,
        analysis: AgentAnalysis,
        configured_weights: dict[str, float],
        known_evidence_ids: Iterable[str],
    ) -> SpecialistAgentResult:
        known = set(known_evidence_ids)
        contributions: list[WeightedItemContribution] = []
        rejected = 0
        for item in analysis.item_scores:
            configured_weight = configured_weights.get(item.item_type)
            if (
                configured_weight is None
                or configured_weight <= 0
                or not set(item.evidence_refs).issubset(known)
            ):
                rejected += 1
                continue
            effective_weight = configured_weight * item.confidence
            contributions.append(
                WeightedItemContribution(
                    item_type=item.item_type,
                    score=item.score,
                    confidence=item.confidence,
                    configured_weight=configured_weight,
                    effective_weight=effective_weight,
                    weighted_contribution=item.score * effective_weight,
                    evidence_refs=item.evidence_refs,
                )
            )

        total_effective_weight = sum(item.effective_weight for item in contributions)
        aggregate = None
        if contributions and total_effective_weight > 0:
            configured_total = sum(configured_weights.values())
            covered_weight = sum(item.configured_weight for item in contributions)
            aggregate = AgentScoreAggregate(
                weighted_score=sum(
                    item.weighted_contribution for item in contributions
                )
                / total_effective_weight,
                confidence=sum(
                    item.configured_weight * item.confidence
                    for item in contributions
                )
                / covered_weight,
                coverage=covered_weight / configured_total,
                total_effective_weight=total_effective_weight,
                contributions=contributions,
            )
        return SpecialistAgentResult(
            agent=agent,
            raw_analysis=analysis,
            score_aggregate=aggregate,
            rejected_item_scores=rejected,
        )


def combine_agent_scores(results: Iterable[SpecialistAgentResult]) -> float | None:
    """Combine specialist aggregates using confidence and category coverage."""
    weighted: list[tuple[float, float]] = []
    for result in results:
        aggregate = result.score_aggregate
        if aggregate is None:
            continue
        weight = aggregate.confidence * aggregate.coverage
        if weight > 0:
            weighted.append((aggregate.weighted_score, weight))
    total_weight = sum(weight for _, weight in weighted)
    if total_weight == 0:
        return None
    return sum(score * weight for score, weight in weighted) / total_weight
