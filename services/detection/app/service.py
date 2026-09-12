from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from app.detectors.anomaly import AnomalyDetector
from app.detectors.llm import LLMDetector, MessageClassifier
from app.detectors.rules import RuleDetector
from app.detectors.registry import DetectorRegistry, RegisteredDetector
from app.domain.context import DetectionContext
from app.domain.models import ComponentResult, DetectionRequest, DetectionResult, DetectionTrigger, Subject
from app.policies.models import AnomalyPolicy, DetectorComponentPolicy, LLMClassifierPolicy, RuleBasedPolicy
from app.policies.repository import FilePolicyRepository
from app.errors import CheckInconclusiveError, CheckUnavailableError


class SubjectNotFoundError(LookupError):
    pass


class ContextRepository(Protocol):
    async def load_context(self, subject: Subject, required_evidence: set[str] | None = None) -> DetectionContext | None: ...


class DetectionService:
    def __init__(
        self,
        repository: ContextRepository,
        classifier: MessageClassifier | None = None,
        policy_repository: FilePolicyRepository | None = None,
        default_policy_version: str = "baseline-v1",
        registry: DetectorRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.classifier = classifier
        self.policy_repository = policy_repository or FilePolicyRepository(
            Path(__file__).resolve().parents[1] / "config" / "policies"
        )
        self.default_policy_version = default_policy_version
        self.registry = registry or self._default_registry()

    def _default_registry(self) -> DetectorRegistry:
        registry = DetectorRegistry()
        registry.register(
            RegisteredDetector(
                "rule_based",
                "builtin-v1",
                frozenset(
                    {
                        "message",
                        "report_record",
                        "login_event",
                        "account_security_event",
                        "product_image",
                        "refund",
                        "dispute",
                        "delivery_event",
                    }
                ),
                lambda config: RuleDetector(RuleBasedPolicy.model_validate(config)),
            )
        )
        registry.register(
            RegisteredDetector(
                "anomaly",
                "builtin-v1",
                frozenset({"payment_attempt", "login_event", "message", "product", "dispute"}),
                lambda config: AnomalyDetector(AnomalyPolicy.model_validate(config)),
            )
        )
        if self.classifier:
            registry.register(
                RegisteredDetector(
                    "llm_classifier",
                    "builtin-v1",
                    frozenset({"message"}),
                    lambda config: LLMDetector(
                        self.classifier,
                        LLMClassifierPolicy.model_validate(config).confidence_threshold,
                    ),
                )
            )
        return registry

    @staticmethod
    def _components(policy, checks, explicitly_requested: bool) -> list[DetectorComponentPolicy]:
        if policy.components and not explicitly_requested:
            return [item for item in policy.components if item.enabled]
        if policy.components:
            by_type = {item.type: item for item in policy.components if item.enabled}
            return [by_type.get(check, DetectorComponentPolicy(id=check, type=check, version="builtin-v1")) for check in checks]
        return [DetectorComponentPolicy(id=check, type=check, version="builtin-v1") for check in checks]

    @staticmethod
    def _config(policy, component: DetectorComponentPolicy) -> dict:
        base = getattr(policy, component.type, None)
        values = base.model_dump(mode="json") if base is not None else {}
        return {**values, **component.config}

    async def detect(self, request: DetectionRequest, policy_override=None) -> DetectionResult:
        policy_version = (
            request.policy_ref.version
            if "policy_ref" in request.model_fields_set
            else self.policy_repository.active_version() or self.default_policy_version
        )
        policy = policy_override or self.policy_repository.resolve(policy_version)
        policy_version = policy.version
        checks = (
            request.requested_checks
            if "requested_checks" in request.model_fields_set
            else policy.default_checks
        )
        if not checks:
            raise CheckUnavailableError("No checks requested")
        if "ml_classifier" in checks:
            raise CheckUnavailableError("ml_classifier is not implemented")
        if "llm_classifier" in checks and self.classifier is None:
            raise CheckUnavailableError("llm_classifier is not configured")
        if "llm_classifier" in checks and self.registry.resolve("llm_classifier", "builtin-v1") is None:
            self.registry.register(
                RegisteredDetector(
                    "llm_classifier",
                    "builtin-v1",
                    frozenset({"message"}),
                    lambda config: LLMDetector(
                        self.classifier,
                        LLMClassifierPolicy.model_validate(config).confidence_threshold,
                    ),
                )
            )
        explicitly_requested = "requested_checks" in request.model_fields_set
        components = self._components(policy, checks, explicitly_requested)
        required_evidence: set[str] = set()
        for component in components:
            registered = self.registry.resolve(component.type, component.version)
            if registered:
                required_evidence.update(registered.required_evidence)
        context = await self.repository.load_context(request.subject, required_evidence)
        if context is None:
            raise SubjectNotFoundError(request.subject.id)

        triggers: list[DetectionTrigger] = []
        component_results: list[ComponentResult] = []
        for component in components:
            started = perf_counter()
            registered = self.registry.resolve(component.type, component.version)
            if registered is None:
                component_results.append(
                    ComponentResult(
                        component_id=component.id,
                        detector=component.type,
                        version=component.version,
                        status="unavailable",
                        trigger_count=0,
                        latency_ms=0,
                        reason="detector_not_registered",
                    )
                )
                continue
            try:
                detector = registered.factory(self._config(policy, component))
                found = await (
                    detector.detect(
                        context.evidence,
                        target_message_id=(request.subject.id if request.subject.type == "message" else None),
                        background=context.conversation_context,
                    )
                    if component.type == "llm_classifier"
                    else detector.detect(context)
                )
                triggers.extend(found)
                component_results.append(
                    ComponentResult(
                        component_id=component.id,
                        detector=component.type,
                        version=component.version,
                        status="completed",
                        trigger_count=len(found),
                        latency_ms=(perf_counter() - started) * 1000,
                    )
                )
            except Exception as exc:
                component_results.append(
                    ComponentResult(
                        component_id=component.id,
                        detector=component.type,
                        version=component.version,
                        status="failed",
                        trigger_count=0,
                        latency_ms=(perf_counter() - started) * 1000,
                        reason=type(exc).__name__,
                    )
                )
                if isinstance(exc, CheckInconclusiveError) and explicitly_requested:
                    raise
                if component.failure_mode == "fail":
                    raise

        triggers = [
            trigger.model_copy(
                update={"raw_result": {**(trigger.raw_result or {}), "policy_version": policy.version}}
            )
            for trigger in triggers
        ]

        referenced = {ref for trigger in triggers for ref in trigger.evidence_refs}
        evidence = [item for item in context.evidence if item.id in referenced]
        return DetectionResult(
            detection_id=f"DET-{uuid4()}",
            subject=request.subject,
            policy_ref={"type": "detection", "version": policy.version},
            detected=bool(triggers),
            triggers=triggers,
            evidence=evidence,
            component_results=component_results,
        )
