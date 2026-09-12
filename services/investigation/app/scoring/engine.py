"""Deterministic scoring; language models never assign the final score."""

from __future__ import annotations

from app.domain.models import Finding, ScoreboardConfig, Verdict


def apply_findings(
    current_score: float,
    findings: list[Finding],
    config: ScoreboardConfig,
) -> tuple[float, float]:
    delta = 0.0
    for finding in findings:
        direction = {
            "supports_fraud": 1.0,
            "supports_legitimate": -1.0,
            "neutral": 0.0,
        }[finding.impact]
        delta += direction * config.finding_weight * finding.confidence
    updated = min(1.0, max(0.0, current_score + delta))
    return updated, updated - current_score


def verdict_for(score: float, config: ScoreboardConfig, has_findings: bool) -> Verdict:
    if score >= config.fraud_threshold:
        return "fraud"
    if score <= config.normal_threshold:
        return "normal"
    if has_findings:
        return "suspicious"
    return "unknown"


def confidence_for(score: float, has_findings: bool) -> float:
    if not has_findings:
        return 0.0
    return round(min(1.0, abs(score - 0.5) * 2), 12)
