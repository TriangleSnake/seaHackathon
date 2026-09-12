from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import (
    BaselineExecutionError,
    DatasetAccessError,
    DetectionHttpError,
    DetectionPolicyNotFoundError,
    DetectionPolicyTraceError,
    DetectionRequestRejectedError,
    DetectionResponseError,
    DetectionTimeoutError,
    DetectionTransportError,
)
from .gates import DetectionGateConfig, DetectionGateProvider
from .models import (
    DetectionCase,
    DetectionInput,
    EvaluationJob,
    PolicyEvaluationOutcome,
    PolicyType,
)
from .settings import DetectionHttpSettings


_DETECTION_POLICY_VERSION_HEADER = "X-Detection-Policy-Version"
_DETECTION_CHECKS = frozenset(
    {"rule_based", "anomaly", "llm_classifier", "ml_classifier"}
)
_SUBJECT_TYPES = frozenset(
    {"account", "shop", "product", "order", "transaction", "message"}
)
_EVIDENCE_SOURCES = frozenset(
    {
        "environment",
        "detection",
        "investigation",
        "patrol",
        "association",
        "external",
    }
)


@dataclass(frozen=True)
class DetectionDecision:
    detected: bool
    trigger_count: int

    def __post_init__(self) -> None:
        if self.trigger_count < 0:
            raise ValueError("trigger_count cannot be negative")
        if not self.detected and self.trigger_count:
            raise ValueError("an undetected decision cannot contain triggers")


class DetectionRunner(Protocol):
    """Executes one immutable policy artifact against label-free case input."""

    def run(self, policy_ref: str, case_input: DetectionInput) -> DetectionDecision: ...


@dataclass(frozen=True)
class DetectionHttpResponse:
    """Small transport-neutral HTTP response used for deterministic tests."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


class DetectionHttpTransport(Protocol):
    def post(
        self,
        url: str,
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> DetectionHttpResponse: ...


class UrllibDetectionHttpTransport:
    """Dependency-free blocking HTTP transport for evaluator worker processes."""

    def post(
        self,
        url: str,
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> DetectionHttpResponse:
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return DetectionHttpResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as exc:
            try:
                return DetectionHttpResponse(
                    status_code=exc.code,
                    headers=dict(exc.headers.items()) if exc.headers else {},
                    body=exc.read(),
                )
            finally:
                exc.close()


class HttpDetectionRunner:
    """Execute one exact Detection policy version through ``POST /detect``.

    Requested checks are immutable runner configuration so baseline and candidate
    executions use the same detectors. The wire request is constructed from an
    explicit allow-list; case facts, evaluation labels, gates, and dataset metadata
    cannot cross the Detection boundary.
    """

    def __init__(
        self,
        requested_checks: tuple[str, ...] | list[str],
        *,
        settings: DetectionHttpSettings | None = None,
        transport: DetectionHttpTransport | None = None,
    ) -> None:
        if isinstance(requested_checks, (str, bytes)):
            raise ValueError("requested_checks must be a sequence of check names")
        checks = tuple(requested_checks)
        if any(not isinstance(check, str) for check in checks):
            raise ValueError("requested_checks must contain only strings")
        unsupported = set(checks) - _DETECTION_CHECKS
        if unsupported:
            raise ValueError(f"Unsupported Detection checks: {sorted(unsupported)}")
        if len(checks) != len(set(checks)):
            raise ValueError("requested_checks must not contain duplicates")

        resolved_settings = settings or DetectionHttpSettings.from_env()
        self._requested_checks = checks
        self._detect_url = f"{resolved_settings.base_url.rstrip('/')}/detect"
        self._timeout_seconds = resolved_settings.timeout_seconds
        self._transport = transport or UrllibDetectionHttpTransport()

    @classmethod
    def from_env(
        cls,
        requested_checks: tuple[str, ...] | list[str],
        *,
        transport: DetectionHttpTransport | None = None,
    ) -> "HttpDetectionRunner":
        return cls(
            requested_checks,
            settings=DetectionHttpSettings.from_env(),
            transport=transport,
        )

    def run(self, policy_ref: str, case_input: DetectionInput) -> DetectionDecision:
        if not isinstance(policy_ref, str) or not policy_ref:
            raise ValueError("Detection policy version must be a non-empty string")

        subject = {"type": case_input.subject_type, "id": case_input.subject_id}
        request = {
            "subject": subject,
            "requested_checks": list(self._requested_checks),
            "policy_ref": {"type": "detection", "version": policy_ref},
            "trigger_context": {
                "source": "api",
                "reason": "baseline_candidate_comparison",
            },
        }

        response = self._post(request, policy_ref)
        _raise_for_detection_status(response, policy_ref)
        result = _parse_detection_result(response.body)
        if result["subject"] != subject:
            raise DetectionResponseError(
                "DetectionResult subject does not match the requested subject"
            )

        actual_version = _header_value(
            response.headers, _DETECTION_POLICY_VERSION_HEADER
        )
        if actual_version is None:
            raise DetectionPolicyTraceError(
                f"Detection response is missing {_DETECTION_POLICY_VERSION_HEADER}"
            )
        if actual_version != policy_ref:
            raise DetectionPolicyTraceError(
                "Detection executed an unexpected policy version: "
                f"requested {policy_ref!r}, response header reported {actual_version!r}"
            )

        detected = result["detected"]
        triggers = result["triggers"]
        if not detected and triggers:
            raise DetectionResponseError(
                "DetectionResult is inconsistent: detected=false with positive triggers"
            )
        trigger_count = max(1, len(triggers)) if detected else 0
        return DetectionDecision(detected=detected, trigger_count=trigger_count)

    def _post(
        self, request: Mapping[str, Any], policy_ref: str
    ) -> DetectionHttpResponse:
        try:
            response = self._transport.post(
                self._detect_url, request, self._timeout_seconds
            )
        except TimeoutError as exc:
            raise DetectionTimeoutError(
                f"Detection timed out while executing policy {policy_ref!r}"
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise DetectionTimeoutError(
                    f"Detection timed out while executing policy {policy_ref!r}"
                ) from exc
            raise DetectionTransportError(
                f"Detection network request failed for policy {policy_ref!r}: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise DetectionTransportError(
                f"Detection network request failed for policy {policy_ref!r}: {exc}"
            ) from exc
        if not isinstance(response, DetectionHttpResponse):
            raise DetectionResponseError(
                "Detection transport returned an invalid response object"
            )
        return response


def _raise_for_detection_status(
    response: DetectionHttpResponse, policy_ref: str
) -> None:
    status_code = response.status_code
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise DetectionResponseError("Detection transport returned an invalid HTTP status")
    if 200 <= status_code < 300:
        return

    error_code, api_message = _decode_api_error(response.body)
    detail = f": {api_message}" if api_message else ""
    if status_code == 404 and error_code == "policy_not_found":
        raise DetectionPolicyNotFoundError(
            f"Detection policy {policy_ref!r} was not found{detail}",
            status_code=status_code,
            error_code=error_code,
        )
    if status_code == 422 or error_code in {
        "subject_not_found",
        "unsupported_subject",
        "unsupported_check",
    }:
        raise DetectionRequestRejectedError(
            f"Detection rejected the evaluation request with HTTP {status_code}"
            f"{_format_error_code(error_code)}{detail}",
            status_code=status_code,
            error_code=error_code,
        )
    raise DetectionHttpError(
        f"Detection failed with HTTP {status_code}{_format_error_code(error_code)}{detail}",
        status_code=status_code,
        error_code=error_code,
    )


def _format_error_code(error_code: str | None) -> str:
    return f" ({error_code})" if error_code else ""


def _decode_api_error(body: bytes) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None, None
    if not isinstance(payload, Mapping):
        return None, None

    error = payload.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        message = error.get("message")
        return (
            code if isinstance(code, str) else None,
            message if isinstance(message, str) else None,
        )

    detail = payload.get("detail")
    if detail is not None:
        return None, json.dumps(detail, separators=(",", ":"))[:500]
    return None, None


def _parse_detection_result(body: bytes) -> Mapping[str, Any]:
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise DetectionResponseError(
            "Detection returned malformed JSON instead of a DetectionResult"
        ) from exc
    _validate_detection_result(result)
    return result


def _validate_detection_result(value: Any) -> None:
    result = _require_object(value, "DetectionResult")
    _require_keys(
        result,
        required={"detection_id", "subject", "detected", "triggers", "evidence"},
        optional=set(),
        path="DetectionResult",
    )
    if not isinstance(result["detection_id"], str):
        _invalid("DetectionResult.detection_id must be a string")
    _validate_subject(result["subject"], "DetectionResult.subject")
    if not isinstance(result["detected"], bool):
        _invalid("DetectionResult.detected must be a boolean")

    triggers = _require_array(result["triggers"], "DetectionResult.triggers")
    for index, trigger in enumerate(triggers):
        _validate_trigger(trigger, f"DetectionResult.triggers[{index}]")

    evidence = _require_array(result["evidence"], "DetectionResult.evidence")
    for index, item in enumerate(evidence):
        _validate_evidence(item, f"DetectionResult.evidence[{index}]")


def _validate_subject(value: Any, path: str) -> None:
    subject = _require_object(value, path)
    _require_keys(subject, required={"type", "id"}, optional=set(), path=path)
    if not isinstance(subject["type"], str) or subject["type"] not in _SUBJECT_TYPES:
        _invalid(f"{path}.type is not supported")
    if not isinstance(subject["id"], str) or not subject["id"]:
        _invalid(f"{path}.id must be a non-empty string")


def _validate_trigger(value: Any, path: str) -> None:
    trigger = _require_object(value, path)
    _require_keys(
        trigger,
        required={"type", "detector", "reason", "evidence_refs"},
        optional={"rule_id", "raw_result"},
        path=path,
    )
    if not isinstance(trigger["type"], str):
        _invalid(f"{path}.type must be a string")
    if (
        not isinstance(trigger["detector"], str)
        or trigger["detector"] not in _DETECTION_CHECKS
    ):
        _invalid(f"{path}.detector is not supported")
    if not isinstance(trigger["reason"], str):
        _invalid(f"{path}.reason must be a string")

    if "rule_id" in trigger and trigger["rule_id"] is not None and not isinstance(
        trigger["rule_id"], str
    ):
        _invalid(f"{path}.rule_id must be a string or null")
    if "raw_result" in trigger and trigger["raw_result"] is not None and not isinstance(
        trigger["raw_result"], Mapping
    ):
        _invalid(f"{path}.raw_result must be an object or null")

    evidence_refs = _require_array(trigger["evidence_refs"], f"{path}.evidence_refs")
    if any(not isinstance(reference, str) for reference in evidence_refs):
        _invalid(f"{path}.evidence_refs must contain only strings")
    if len(evidence_refs) != len(set(evidence_refs)):
        _invalid(f"{path}.evidence_refs must contain unique values")


def _validate_evidence(value: Any, path: str) -> None:
    evidence = _require_object(value, path)
    _require_keys(
        evidence,
        required={"id", "source", "type", "data"},
        optional={"ref_id", "observed_at"},
        path=path,
    )
    for key in ("id", "type"):
        if not isinstance(evidence[key], str) or not evidence[key]:
            _invalid(f"{path}.{key} must be a non-empty string")
    if (
        not isinstance(evidence["source"], str)
        or evidence["source"] not in _EVIDENCE_SOURCES
    ):
        _invalid(f"{path}.source is not supported")
    if "ref_id" in evidence and evidence["ref_id"] is not None and not isinstance(
        evidence["ref_id"], str
    ):
        _invalid(f"{path}.ref_id must be a string or null")
    if (
        "observed_at" in evidence
        and evidence["observed_at"] is not None
        and not isinstance(evidence["observed_at"], str)
    ):
        _invalid(f"{path}.observed_at must be a string or null")
    if not isinstance(evidence["data"], Mapping):
        _invalid(f"{path}.data must be an object")


def _require_object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(f"{path} must be an object")
    return value


def _require_array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _invalid(f"{path} must be an array")
    return value


def _require_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    path: str,
) -> None:
    missing = required - set(value)
    if missing:
        _invalid(f"{path} is missing fields: {sorted(missing)}")
    unexpected = set(value) - required - optional
    if unexpected:
        _invalid(f"{path} has unexpected fields: {sorted(unexpected)}")


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    if not isinstance(headers, Mapping):
        raise DetectionResponseError("Detection response headers are invalid")
    lower_name = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == lower_name:
            if not isinstance(value, str):
                raise DetectionResponseError(
                    f"Detection response header {name} is not a string"
                )
            return value
    return None


def _invalid(message: str) -> NoReturn:
    raise DetectionResponseError(f"Invalid DetectionResult: {message}")


class ContractDetectionRunner:
    """Adapter for a future Detection runtime using the shared Detection contracts.

    The executor owns artifact loading and runtime transport. The adapter passes only
    the schema-defined subject request and translates the returned DetectionResult;
    it never implements detection logic itself.
    """

    def __init__(
        self,
        executor: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
    ) -> None:
        self._executor = executor

    def run(self, policy_ref: str, case_input: DetectionInput) -> DetectionDecision:
        request = {
            "subject": {
                "type": case_input.subject_type,
                "id": case_input.subject_id,
            },
            "trigger_context": {"source": "scheduled", "reason": "evaluation"},
        }
        result = self._executor(policy_ref, request)
        detected = result.get("detected")
        triggers = result.get("triggers")
        if not isinstance(detected, bool) or not isinstance(triggers, list):
            raise ValueError("Detection runtime returned an invalid DetectionResult")
        # A positive DetectionResult is one review trigger even if a runtime omits
        # trigger details. Multiple detector triggers remain visible as extra volume.
        trigger_count = max(1, len(triggers)) if detected else 0
        return DetectionDecision(detected=detected, trigger_count=trigger_count)


@dataclass(frozen=True)
class _DetectionStats:
    metrics: "DetectionMetrics"
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int


@dataclass(frozen=True)
class DetectionMetrics:
    precision: float
    recall: float | None
    f1: float | None
    false_positive_count: int
    false_positive_rate: float
    trigger_volume: int

    def to_mapping(self) -> dict[str, float | int | None]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "false_positive_count": self.false_positive_count,
            "false_positive_rate": self.false_positive_rate,
            "trigger_volume": self.trigger_volume,
        }


class DetectionPolicyEvaluator:
    policy_type = PolicyType.DETECTION

    def __init__(
        self,
        runner: DetectionRunner,
        gate_provider: DetectionGateProvider,
    ) -> None:
        self._runner = runner
        self._gate_provider = gate_provider

    def evaluate(self, job: EvaluationJob) -> PolicyEvaluationOutcome:
        cases = _detection_cases(job)
        baseline_decisions = self._run_baseline(job, cases)
        baseline_stats = _calculate_stats(cases, baseline_decisions)

        try:
            candidate_decisions = tuple(
                self._validated_decision(
                    self._runner.run(job.plan.candidate_policy_ref, case.input)
                )
                for case in cases
            )
        except Exception as exc:  # Runtime boundary: implementation validity failure.
            return PolicyEvaluationOutcome(
                passed=False,
                implementation_valid=False,
                candidate_metrics=_empty_metrics().to_mapping(),
                baseline_metrics=baseline_stats.metrics.to_mapping(),
                incremental_value={},
                failure_reasons=(
                    f"Candidate implementation failed: {type(exc).__name__}: {exc}",
                ),
            )

        candidate_stats = _calculate_stats(cases, candidate_decisions)
        incremental = _calculate_incremental(
            cases, baseline_decisions, candidate_decisions, baseline_stats, candidate_stats
        )
        regressions = _describe_regressions(incremental)
        failure_reasons = _apply_gates(
            self._gate_provider.get(), candidate_stats.metrics, incremental
        )
        return PolicyEvaluationOutcome(
            passed=not failure_reasons,
            implementation_valid=True,
            candidate_metrics=candidate_stats.metrics.to_mapping(),
            baseline_metrics=baseline_stats.metrics.to_mapping(),
            incremental_value=incremental,
            regressions=regressions,
            failure_reasons=failure_reasons,
        )

    def _run_baseline(
        self, job: EvaluationJob, cases: tuple[DetectionCase, ...]
    ) -> tuple[DetectionDecision, ...]:
        try:
            return tuple(
                self._validated_decision(
                    self._runner.run(job.plan.baseline_policy_ref, case.input)
                )
                for case in cases
            )
        except Exception as exc:
            raise BaselineExecutionError(
                f"Baseline policy {job.plan.baseline_policy_ref!r} could not run: {exc}"
            ) from exc

    @staticmethod
    def _validated_decision(decision: DetectionDecision) -> DetectionDecision:
        if not isinstance(decision, DetectionDecision):
            raise TypeError("Detection runner must return DetectionDecision")
        return decision


def _detection_cases(job: EvaluationJob) -> tuple[DetectionCase, ...]:
    cases: list[DetectionCase] = []
    seen_ids: set[str] = set()
    for dataset in job.datasets:
        for record in dataset.records:
            if not isinstance(record, DetectionCase):
                raise DatasetAccessError(
                    f"Dataset {dataset.ref.ref!r} contains a non-detection record"
                )
            if record.input.case_id in seen_ids:
                raise DatasetAccessError(
                    f"Duplicate case_id across evaluation datasets: {record.input.case_id}"
                )
            seen_ids.add(record.input.case_id)
            cases.append(record)
    if not cases:
        raise DatasetAccessError("Detection evaluation requires at least one case")
    return tuple(cases)


def _calculate_stats(
    cases: tuple[DetectionCase, ...], decisions: tuple[DetectionDecision, ...]
) -> _DetectionStats:
    if len(cases) != len(decisions):
        raise ValueError("Every case must have exactly one decision")

    tp = fp = tn = fn = 0
    for case, decision in zip(cases, decisions, strict=True):
        if case.is_fraud is True:
            if decision.detected:
                tp += 1
            else:
                fn += 1
        elif case.is_fraud is False:
            if decision.detected:
                fp += 1
            else:
                tn += 1

    precision = _ratio(tp, tp + fp, default=0.0)
    recall = _ratio(tp, tp + fn, default=None)
    if recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    metrics = DetectionMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_count=fp,
        # The shared schema does not permit null here; zero is the neutral value
        # when a dataset contains no labelled negatives.
        false_positive_rate=_ratio(fp, fp + tn, default=0.0),
        trigger_volume=sum(decision.trigger_count for decision in decisions),
    )
    return _DetectionStats(
        metrics=metrics,
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
    )


def _calculate_incremental(
    cases: tuple[DetectionCase, ...],
    baseline: tuple[DetectionDecision, ...],
    candidate: tuple[DetectionDecision, ...],
    baseline_stats: _DetectionStats,
    candidate_stats: _DetectionStats,
) -> dict[str, int | float | None]:
    new_fraud_hits = additional_false_positives = fraud_hits_lost = 0
    false_positives_removed = 0
    for case, old, new in zip(cases, baseline, candidate, strict=True):
        if case.is_fraud is True:
            new_fraud_hits += int(new.detected and not old.detected)
            fraud_hits_lost += int(old.detected and not new.detected)
        elif case.is_fraud is False:
            additional_false_positives += int(new.detected and not old.detected)
            false_positives_removed += int(old.detected and not new.detected)

    old_metrics = baseline_stats.metrics
    new_metrics = candidate_stats.metrics
    return {
        "new_fraud_hits": new_fraud_hits,
        "additional_false_positives": additional_false_positives,
        "fraud_hits_lost": fraud_hits_lost,
        "false_positives_removed": false_positives_removed,
        "trigger_volume_delta": new_metrics.trigger_volume - old_metrics.trigger_volume,
        "precision_delta": new_metrics.precision - old_metrics.precision,
        "recall_delta": _optional_delta(new_metrics.recall, old_metrics.recall),
        "f1_delta": _optional_delta(new_metrics.f1, old_metrics.f1),
        "false_positive_count_delta": (
            new_metrics.false_positive_count - old_metrics.false_positive_count
        ),
        "false_positive_rate_delta": (
            new_metrics.false_positive_rate - old_metrics.false_positive_rate
        ),
    }


def _describe_regressions(
    incremental: Mapping[str, int | float | None],
) -> tuple[str, ...]:
    regressions: list[str] = []
    lost = int(incremental["fraud_hits_lost"] or 0)
    added_fp = int(incremental["additional_false_positives"] or 0)
    volume_delta = int(incremental["trigger_volume_delta"] or 0)
    precision_delta = incremental["precision_delta"]
    recall_delta = incremental["recall_delta"]

    if lost:
        regressions.append(f"Candidate loses {lost} fraud hits relative to baseline.")
    if added_fp:
        regressions.append(
            f"Candidate adds {added_fp} false positives relative to baseline."
        )
    if isinstance(precision_delta, (int, float)) and precision_delta < 0:
        regressions.append(f"Candidate precision decreases by {abs(precision_delta):.3f}.")
    if isinstance(recall_delta, (int, float)) and recall_delta < 0:
        regressions.append(f"Candidate recall decreases by {abs(recall_delta):.3f}.")
    if volume_delta > 0:
        regressions.append(f"Candidate trigger volume increases by {volume_delta}.")
    return tuple(regressions)


def _apply_gates(
    gates: DetectionGateConfig,
    candidate: DetectionMetrics,
    incremental: Mapping[str, int | float | None],
) -> tuple[str, ...]:
    failures: list[str] = []
    added_fp = int(incremental["additional_false_positives"] or 0)
    lost = int(incremental["fraud_hits_lost"] or 0)
    volume_delta = int(incremental["trigger_volume_delta"] or 0)
    recall_delta = incremental["recall_delta"]

    if candidate.precision < gates.minimum_precision:
        failures.append(
            f"Precision {candidate.precision:.3f} is below temporary minimum "
            f"{gates.minimum_precision:.3f}."
        )
    if candidate.false_positive_rate > gates.maximum_false_positive_rate:
        failures.append(
            f"False-positive rate {candidate.false_positive_rate:.3f} exceeds temporary "
            f"maximum {gates.maximum_false_positive_rate:.3f}."
        )
    if added_fp > gates.maximum_additional_false_positives:
        failures.append(
            f"Candidate adds {added_fp} false positives; temporary maximum is "
            f"{gates.maximum_additional_false_positives}."
        )
    if lost > gates.maximum_fraud_hits_lost:
        failures.append(
            f"Candidate loses {lost} fraud hits; temporary maximum is "
            f"{gates.maximum_fraud_hits_lost}."
        )
    if volume_delta > gates.maximum_trigger_volume_delta:
        failures.append(
            f"Trigger-volume delta {volume_delta} exceeds temporary maximum "
            f"{gates.maximum_trigger_volume_delta}."
        )
    if isinstance(recall_delta, (int, float)) and recall_delta < gates.minimum_recall_delta:
        failures.append(
            f"Recall delta {recall_delta:.3f} is below temporary minimum "
            f"{gates.minimum_recall_delta:.3f}."
        )
    if gates.require_incremental_improvement:
        new_hits = int(incremental["new_fraud_hits"] or 0)
        removed_fp = int(incremental["false_positives_removed"] or 0)
        if new_hits == 0 and removed_fp == 0:
            failures.append(
                "Candidate provides no incremental fraud hits or false-positive reduction."
            )
    return tuple(failures)


def _ratio(numerator: int, denominator: int, default: float | None) -> float | None:
    return numerator / denominator if denominator else default


def _optional_delta(new: float | None, old: float | None) -> float | None:
    if new is None or old is None:
        return None
    return new - old


def _empty_metrics() -> DetectionMetrics:
    return DetectionMetrics(
        precision=0.0,
        recall=None,
        f1=None,
        false_positive_count=0,
        false_positive_rate=0.0,
        trigger_volume=0,
    )
