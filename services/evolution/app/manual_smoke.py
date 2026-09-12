"""Optional live smoke for the real OpenAI Evolution planner.

Run from ``services/evolution`` with ``OPENAI_API_KEY`` configured:

    python3 -m app.manual_smoke

This intentionally stops before capability resolution or candidate building.
"""

from __future__ import annotations

import json

from .adapters import SharedContractAdapter
from .domain import EvolutionRun
from .planner import OpenAIEvolutionPlanner, PlannerError


def manual_evolution_request() -> dict:
    """Return a shared-schema-compatible request without demo-specific answers."""

    return {
        "trigger": {
            "type": "new_spec_ready",
            "context": {"source": "manual-real-planner-smoke"},
        },
        "current_defense_version": {"version": "DV-MANUAL-BASE"},
        "system_performance": {
            "precision": 0.72,
            "false_positive_rate": 0.08,
        },
        "pattern_spec": {
            "pattern_id": "manual-pattern",
            "name": "Previously unseen chat request wording",
            "description": (
                "A suspicious request uses wording not represented by the active "
                "detection configuration."
            ),
            "observed_signals": [
                {
                    "field": "message.text",
                    "operator": "contains",
                    "value": "unseen off-platform request wording",
                    "description": "Manual smoke input, not an expected answer",
                }
            ],
            "current_defense_gap": (
                "The current phrase-list behavior does not cover this wording."
            ),
            "confidence": 0.9,
            "evidence_refs": ["manual-evidence-ref"],
        },
    }


def main() -> None:
    try:
        planner = OpenAIEvolutionPlanner.from_env()
        context = SharedContractAdapter().evolution_context(manual_evolution_request())
        run = EvolutionRun(
            run_id="manual-real-planner-smoke",
            trigger_source=context.trigger_type.value,
        )
        diagnosis = planner.diagnose(context)
        result: dict = {"diagnosis": _diagnosis_json(diagnosis)}
        if diagnosis.primary_gap is not None:
            result["proposal"] = _proposal_json(
                planner.propose(run, context, diagnosis)
            )
    except PlannerError as exc:
        raise SystemExit(f"Real Evolution planner smoke could not run: {exc}") from None
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def _diagnosis_json(diagnosis) -> dict:
    return {
        "outcome": diagnosis.outcome.value,
        "reason": diagnosis.reason,
        "primary_gap_index": diagnosis.primary_gap_index,
        "considered_policies": [item.value for item in diagnosis.considered_policies],
        "policy_gaps": [
            {
                "policy_type": gap.policy_type.value,
                "severity": gap.severity.value,
                "confidence": gap.confidence,
                "symptom": gap.symptom,
                "hypothesized_cause": gap.hypothesized_cause,
                "evidence_refs": list(gap.evidence_refs),
                "reasoning": gap.reasoning,
            }
            for gap in diagnosis.policy_gaps
        ],
    }


def _proposal_json(proposal) -> dict:
    intent = proposal.mutation_intent
    return {
        "proposal_id": proposal.proposal_id,
        "target_policy": proposal.target_policy.value,
        "base_defense_version": proposal.base_defense_version,
        "objective": proposal.objective,
        "requested_behavior": proposal.requested_behavior,
        "required_signals": list(proposal.required_signals),
        "expected_impact": proposal.expected_impact,
        "known_risks": list(proposal.known_risks),
        "mutation_intent": (
            {
                "operation": intent.operation,
                "path": intent.path,
                "values": list(intent.values),
                "rationale": intent.rationale,
            }
            if intent is not None
            else None
        ),
        "provenance": dict(proposal.provenance),
    }


if __name__ == "__main__":
    main()
