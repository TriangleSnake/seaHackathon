from __future__ import annotations

from hashlib import sha256
from typing import Iterable

from .models import (
    AssociationRequest,
    AssociationResult,
    Evidence,
    Indicator,
    InvestigationRequest,
    InvestigationWithProvenance,
    PatrolDiscovery,
    PatrolResult,
    UpstreamPipelineResult,
)


class AdapterError(ValueError):
    pass


def deterministic_case_id(result: PatrolResult, discovery: PatrolDiscovery) -> str:
    key = f"{result.run_id}:{discovery.subject.type}:{discovery.subject.id}"
    return f"patrol-{sha256(key.encode()).hexdigest()[:20]}"


def deterministic_pipeline_run_id(patrol_run_id: str) -> str:
    return f"upstream-{sha256(patrol_run_id.encode()).hexdigest()[:20]}"


_INDICATOR_KEYS = {
    "device_id": "device",
    "ip_address": "ip",
    "payment_instrument_hash": "payment_account",
}


def _seed_indicators(evidence: Iterable[Evidence]) -> list[Indicator]:
    """Map only canonical evidence keys supported by Association's Indicator contract."""
    collected: dict[tuple[str, str], list[str]] = {}
    for item in evidence:
        for key, indicator_type in _INDICATOR_KEYS.items():
            value = item.data.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            refs = collected.setdefault((indicator_type, value), [])
            if item.id not in refs:
                refs.append(item.id)
    return [
        Indicator(type=indicator_type, value=value, evidence_refs=refs)
        for (indicator_type, value), refs in collected.items()
    ]


def discovery_evidence(result: PatrolResult, discovery: PatrolDiscovery) -> list[Evidence]:
    evidence_by_id: dict[str, Evidence] = {}
    for item in result.evidence:
        if item.id in evidence_by_id:
            raise AdapterError(f"Patrol result contains duplicate evidence id {item.id!r}")
        evidence_by_id[item.id] = item
    missing = [ref for ref in discovery.evidence_refs if ref not in evidence_by_id]
    if missing:
        raise AdapterError(f"Patrol discovery references missing evidence: {missing}")
    allowed = set(discovery.evidence_refs)
    for signal in discovery.observed_signals:
        invalid = [ref for ref in signal.evidence_refs if ref not in allowed]
        if invalid:
            raise AdapterError(
                f"Patrol signal {signal.name!r} references evidence outside the discovery: {invalid}"
            )
    return [evidence_by_id[ref] for ref in discovery.evidence_refs]


def build_association_request(
    result: PatrolResult, discovery: PatrolDiscovery
) -> AssociationRequest:
    evidence = discovery_evidence(result, discovery)
    return AssociationRequest(
        case_id=deterministic_case_id(result, discovery),
        subject=discovery.subject,
        strategy="focused",
        seed_indicators=_seed_indicators(evidence),
    )


def _association_evidence(
    patrol_evidence: list[Evidence], association: AssociationResult
) -> list[Evidence]:
    """Return compatible Association evidence while rejecting ID collisions."""
    patrol_by_id = {item.id: item for item in patrol_evidence}
    selected: dict[str, Evidence] = {}
    for item in association.evidence:
        previous = patrol_by_id.get(item.id) or selected.get(item.id)
        if previous is not None:
            if previous != item:
                raise AdapterError(
                    f"Evidence id {item.id!r} has conflicting Patrol/Association payloads"
                )
            continue
        selected[item.id] = item
    return list(selected.values())


def build_investigation_request(
    result: PatrolResult,
    discovery: PatrolDiscovery,
    association: AssociationResult,
    scoreboard_config_version: str,
) -> InvestigationRequest:
    case_id = deterministic_case_id(result, discovery)
    if association.case_id != case_id:
        raise AdapterError("Association result case_id does not match discovery lineage")
    if association.strategy != "focused":
        raise AdapterError("Association result strategy does not match focused request")

    patrol_evidence = discovery_evidence(result, discovery)
    trigger_context = {
        "source": "patrol",
        "run_id": result.run_id,
        "strategy": result.strategy,
        "policy_ref": result.policy_ref.model_dump(mode="json"),
        "hypothesis": discovery.hypothesis,
        "reason": discovery.reason,
        "counter_signals": discovery.counter_signals,
        "priority": discovery.priority,
    }
    detection_policy_version = (
        f"patrol-adapter-v1/{result.policy_ref.id}/{result.policy_ref.version}"
    )
    return InvestigationRequest.model_validate(
        {
            "case_id": case_id,
            "detection_result": {
                "detection_id": (
                    f"patrol:{result.run_id}:{discovery.subject.type}:{discovery.subject.id}"
                ),
                "subject": discovery.subject.model_dump(mode="json"),
                "policy_ref": {
                    "type": "detection",
                    "version": detection_policy_version,
                },
                "detected": True,
                "triggers": [
                    {
                        "type": signal.name,
                        "detector": "anomaly",
                        "reason": signal.description,
                        "raw_result": trigger_context,
                        "evidence_refs": signal.evidence_refs,
                    }
                    for signal in discovery.observed_signals
                ],
                "evidence": [item.model_dump(mode="json") for item in patrol_evidence],
                "component_results": [
                    {
                        "component_id": "patrol-upstream-discovery",
                        "detector": "anomaly",
                        "version": "1",
                        "status": "completed",
                        "trigger_count": len(discovery.observed_signals),
                        "latency_ms": 0,
                        "reason": "Promoted from an evidence-backed Patrol discovery",
                    }
                ],
            },
            "existing_evidence": [
                item.model_dump(mode="json")
                for item in _association_evidence(patrol_evidence, association)
            ],
            "scoreboard_config_ref": {"version": scoreboard_config_version},
        }
    )


def collect_investigation_results(
    pipeline_result: UpstreamPipelineResult,
) -> list[InvestigationWithProvenance]:
    """Clean Pattern Synthesis handoff: successful results plus upstream provenance."""
    handoff: list[InvestigationWithProvenance] = []
    for item in pipeline_result.discoveries:
        if (
            item.association.status != "succeeded"
            or item.association.result is None
            or item.investigation.status != "succeeded"
            or item.investigation.result is None
        ):
            continue
        handoff.append(
            InvestigationWithProvenance(
                patrol_run_id=pipeline_result.patrol_run_id,
                case_id=item.case_id,
                subject=item.subject,
                patrol_discovery=item.patrol_discovery,
                association=item.association.result,
                investigation_result=item.investigation.result,
            )
        )
    return handoff
