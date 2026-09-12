"""Deterministic provenance and PatternSpec validation."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, NoReturn

from .contracts import SharedContractError, SharedContractValidator
from .errors import SynthesisError
from .models import (
    BehaviorProvenance,
    BehaviorStep,
    ObservedSignal,
    PatternSpec,
    PatternSynthesisRequest,
    SemanticPatternDraft,
    SignalProvenance,
    SynthesisProvenance,
)


def _duplicates(values: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _literal_occurs(value: Any, literal: str) -> bool:
    if isinstance(value, str):
        return literal in value
    if isinstance(value, dict):
        return any(_literal_occurs(item, literal) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_literal_occurs(item, literal) for item in value)
    return value == literal


class PatternValidator:
    def __init__(self, contracts: SharedContractValidator | None = None) -> None:
        self._contracts = contracts or SharedContractValidator()

    def _fail(self, code: str, message: str, *issues: str) -> NoReturn:
        raise SynthesisError(code, message, tuple(issues))

    def validate_investigations(self, request: PatternSynthesisRequest) -> None:
        evidence_seen: dict[str, str] = {}
        for result in (*request.candidate_results, *request.counterexample_results):
            try:
                self._contracts.investigation_result(result.model_dump(mode="json"))
            except SharedContractError as exc:
                self._fail(
                    "invalid_investigation_contract",
                    f"InvestigationResult {result.case_id} violates the shared contract",
                    *exc.issues,
                )
            local_ids = {item.id for item in result.evidence}
            if len(local_ids) != len(result.evidence):
                self._fail(
                    "ambiguous_evidence_id",
                    f"InvestigationResult {result.case_id} repeats an evidence ID",
                )
            for finding in result.findings:
                missing = set(finding.evidence_refs) - local_ids
                if missing:
                    self._fail(
                        "invalid_investigation_provenance",
                        f"Finding in {result.case_id} references missing evidence",
                        *sorted(missing),
                    )
            for evidence in result.evidence:
                previous = evidence_seen.get(evidence.id)
                if previous is not None:
                    self._fail(
                        "ambiguous_evidence_id",
                        "Evidence IDs must be globally unique across the synthesis bundle",
                        f"{evidence.id}: {previous}, {result.case_id}",
                    )
                evidence_seen[evidence.id] = result.case_id

    def validate(
        self, draft: SemanticPatternDraft, request: PatternSynthesisRequest
    ) -> tuple[PatternSpec, SynthesisProvenance]:
        positive = {item.case_id: item for item in request.candidate_results}
        negative = {item.case_id: item for item in request.counterexample_results}
        all_evidence = {
            evidence.id: (result.case_id, evidence)
            for result in (*request.candidate_results, *request.counterexample_results)
            for evidence in result.evidence
        }

        for label, values in (
            ("supporting_cases", draft.supporting_cases),
            ("counterexamples", draft.counterexamples),
            ("evidence_refs", draft.evidence_refs),
            ("defense_capability_refs", draft.defense_capability_refs),
        ):
            duplicates = _duplicates(values)
            if duplicates:
                self._fail("duplicate_reference", f"{label} contains duplicates", *duplicates)

        unknown_support = set(draft.supporting_cases) - positive.keys()
        if unknown_support:
            self._fail(
                "unknown_supporting_case",
                "supporting_cases contains a case not supplied as suspicious/fraud",
                *sorted(unknown_support),
            )
        if len(set(draft.supporting_cases)) < 2:
            self._fail(
                "insufficient_supporting_cases",
                "A reusable pattern requires at least two supplied suspicious/fraud cases",
            )
        unknown_counters = set(draft.counterexamples) - negative.keys()
        if unknown_counters:
            self._fail(
                "unknown_counterexample",
                "counterexamples contains a case not supplied as normal",
                *sorted(unknown_counters),
            )
        missing_counters = negative.keys() - set(draft.counterexamples)
        if missing_counters:
            self._fail(
                "missing_counterexample",
                "Every supplied normal counterexample must remain a counterexample",
                *sorted(missing_counters),
            )
        if set(draft.supporting_cases) & set(draft.counterexamples):
            self._fail(
                "case_role_conflict", "A case cannot support and counterexample a pattern"
            )

        unknown_evidence = set(draft.evidence_refs) - all_evidence.keys()
        if unknown_evidence:
            self._fail(
                "unknown_evidence_ref",
                "Pattern evidence_refs contains evidence not supplied by Investigation",
                *sorted(unknown_evidence),
            )

        support_set = set(draft.supporting_cases)
        wrong_case_evidence = [
            ref
            for ref in draft.evidence_refs
            if ref in all_evidence and all_evidence[ref][0] not in support_set
        ]
        if wrong_case_evidence:
            self._fail(
                "non_supporting_evidence_ref",
                "Pattern evidence must originate from selected supporting cases",
                *wrong_case_evidence,
            )

        used_refs: set[str] = set()
        multi_case_signal = False
        signal_provenance: list[SignalProvenance] = []
        for index, signal in enumerate(draft.observed_signals):
            duplicates = _duplicates(signal.evidence_refs)
            if duplicates:
                self._fail(
                    "duplicate_reference",
                    f"observed_signals[{index}].evidence_refs contains duplicates",
                    *duplicates,
                )
            unknown = set(signal.evidence_refs) - set(draft.evidence_refs)
            if unknown:
                self._fail(
                    "unsupported_signal_provenance",
                    f"observed_signals[{index}] cites evidence outside pattern evidence_refs",
                    *sorted(unknown),
                )
            cases = tuple(
                sorted({all_evidence[ref][0] for ref in signal.evidence_refs if ref in all_evidence})
            )
            if not cases or not set(cases).issubset(support_set):
                self._fail(
                    "unsupported_signal_provenance",
                    f"observed_signals[{index}] is not grounded by supporting cases",
                )
            if signal.grounding_kind == "semantic" and len(cases) >= 2:
                multi_case_signal = True
            if signal.grounding_kind == "literal":
                if not isinstance(signal.value, str):
                    self._fail(
                        "unsupported_literal_signal",
                        f"observed_signals[{index}] literal value must be a string",
                    )
                literal = signal.value
                if not any(
                    _literal_occurs(all_evidence[ref][1].data, literal)
                    for ref in signal.evidence_refs
                ):
                    self._fail(
                        "unsupported_literal_signal",
                        f"observed_signals[{index}] literal does not occur in cited evidence",
                        literal,
                    )
            used_refs.update(signal.evidence_refs)
            signal_provenance.append(
                SignalProvenance(
                    signal_index=index,
                    grounding_kind=signal.grounding_kind,
                    evidence_refs=signal.evidence_refs,
                    supporting_cases=cases,
                )
            )
        if not multi_case_signal:
            self._fail(
                "no_cross_case_signal",
                "At least one semantic signal must be grounded across multiple supporting cases",
            )

        orders = tuple(step.order for step in draft.behavior_sequence)
        if orders and (len(orders) != len(set(orders)) or sorted(orders) != list(range(1, len(orders) + 1))):
            self._fail(
                "invalid_behavior_sequence",
                "Behavior step order must be unique and contiguous from 1",
            )
        behavior_provenance: list[BehaviorProvenance] = []
        for step in draft.behavior_sequence:
            duplicates = _duplicates(step.evidence_refs)
            if duplicates:
                self._fail(
                    "duplicate_reference",
                    f"behavior step {step.order} evidence_refs contains duplicates",
                    *duplicates,
                )
            unknown = set(step.evidence_refs) - set(draft.evidence_refs)
            if unknown:
                self._fail(
                    "unsupported_behavior_provenance",
                    f"behavior step {step.order} cites evidence outside pattern evidence_refs",
                    *sorted(unknown),
                )
            cases = tuple(
                sorted({all_evidence[ref][0] for ref in step.evidence_refs if ref in all_evidence})
            )
            if not cases or not set(cases).issubset(support_set):
                self._fail(
                    "unsupported_behavior_provenance",
                    f"behavior step {step.order} is not grounded by supporting cases",
                )
            used_refs.update(step.evidence_refs)
            behavior_provenance.append(
                BehaviorProvenance(
                    step_order=step.order,
                    evidence_refs=step.evidence_refs,
                    supporting_cases=cases,
                )
            )

        if used_refs != set(draft.evidence_refs):
            self._fail(
                "unused_pattern_evidence",
                "Pattern evidence_refs must exactly equal signal/behavior provenance",
                *sorted(set(draft.evidence_refs) - used_refs),
            )
        cases_with_evidence = {all_evidence[ref][0] for ref in draft.evidence_refs}
        unsupported_cases = support_set - cases_with_evidence
        if unsupported_cases:
            self._fail(
                "unsupported_supporting_case",
                "Every supporting case must contribute cited evidence",
                *sorted(unsupported_cases),
            )

        allowed_capabilities = {
            item.capability_id for item in request.policy_capability_summary.capabilities
        }
        unknown_capabilities = set(draft.defense_capability_refs) - allowed_capabilities
        if unknown_capabilities:
            self._fail(
                "unknown_defense_capability",
                "current_defense_gap references an unknown defense capability",
                *sorted(unknown_capabilities),
            )

        identity_payload = {
            "synthesis_id": request.synthesis_id,
            "supporting_cases": sorted(draft.supporting_cases),
            "signals": [
                {
                    "field": signal.field,
                    "operator": signal.operator,
                    "value": signal.value,
                }
                for signal in draft.observed_signals
            ],
        }
        digest = sha256(
            json.dumps(
                identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()[:16]
        pattern = PatternSpec(
            pattern_id=f"PAT-{digest}",
            name=draft.name,
            description=draft.description,
            observed_signals=tuple(
                ObservedSignal(
                    field=item.field,
                    operator=item.operator,
                    value=item.value,
                    description=item.description,
                )
                for item in draft.observed_signals
            ),
            behavior_sequence=tuple(
                BehaviorStep(
                    order=item.order,
                    action=item.action,
                    description=item.description,
                )
                for item in draft.behavior_sequence
            ),
            supporting_cases=draft.supporting_cases,
            counterexamples=draft.counterexamples,
            current_defense_gap=draft.current_defense_gap,
            evidence_refs=draft.evidence_refs,
            confidence=draft.confidence,
        )
        try:
            self._contracts.pattern_spec(pattern.model_dump(mode="json"))
        except SharedContractError as exc:
            self._fail(
                "invalid_pattern_contract",
                "Synthesized PatternSpec violates the shared contract",
                *exc.issues,
            )

        provenance = SynthesisProvenance(
            synthesis_id=request.synthesis_id,
            candidate_case_ids=tuple(item.case_id for item in request.candidate_results),
            counterexample_case_ids=tuple(
                item.case_id for item in request.counterexample_results
            ),
            evidence_case_map={
                ref: all_evidence[ref][0] for ref in draft.evidence_refs
            },
            active_defense_version=request.active_defense_version,
            active_policy_refs=request.active_policy_refs,
            defense_capability_refs=draft.defense_capability_refs,
            signal_grounding=tuple(signal_provenance),
            behavior_grounding=tuple(behavior_provenance),
        )
        return pattern, provenance
