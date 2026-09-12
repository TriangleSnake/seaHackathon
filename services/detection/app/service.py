from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.detectors.anomaly import AnomalyDetector
from app.detectors.llm import LLMDetector, MessageClassifier
from app.detectors.rules import RuleDetector
from app.domain.context import DetectionContext
from app.domain.models import DetectionRequest, DetectionResult, DetectionTrigger, Subject
from app.policies.repository import FilePolicyRepository
from app.errors import CheckUnavailableError


class SubjectNotFoundError(LookupError):
    pass


class ContextRepository(Protocol):
    async def load_context(self, subject: Subject) -> DetectionContext | None: ...


class DetectionService:
    def __init__(
        self,
        repository: ContextRepository,
        classifier: MessageClassifier | None = None,
        policy_repository: FilePolicyRepository | None = None,
        default_policy_version: str = "baseline-v1",
    ) -> None:
        self.repository = repository
        self.classifier = classifier
        self.policy_repository = policy_repository or FilePolicyRepository(
            Path(__file__).resolve().parents[1] / "config" / "policies"
        )
        self.default_policy_version = default_policy_version

    async def detect(self, request: DetectionRequest) -> DetectionResult:
        policy_version = (
            request.policy_ref.version
            if "policy_ref" in request.model_fields_set
            else self.default_policy_version
        )
        policy = self.policy_repository.resolve(policy_version)
        context = await self.repository.load_context(request.subject)
        if context is None:
            raise SubjectNotFoundError(request.subject.id)
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

        detectors = {
            "rule_based": RuleDetector(policy.rule_based),
            "anomaly": AnomalyDetector(policy.anomaly, context.as_of),
        }
        llm_detector = (
            LLMDetector(self.classifier, policy.llm_classifier.confidence_threshold)
            if self.classifier
            else None
        )

        triggers: list[DetectionTrigger] = []
        for check in checks:
            if check in detectors:
                triggers.extend(await detectors[check].detect(context))
            elif check == "llm_classifier" and llm_detector:
                triggers.extend(await llm_detector.detect(
                    context.evidence,
                    target_message_id=request.subject.id if request.subject.type == "message" else None,
                    background=context.conversation_context,
                ))

        triggers = [
            trigger.model_copy(
                update={"raw_result": {**(trigger.raw_result or {}), "policy_version": policy.version, "as_of": context.as_of.isoformat()}}
            )
            for trigger in triggers
        ]

        referenced = {ref for trigger in triggers for ref in trigger.evidence_refs}
        evidence = [item for item in context.evidence + context.conversation_context if item.id in referenced]
        return DetectionResult(
            detection_id=f"DET-{uuid4()}",
            subject=request.subject,
            detected=bool(triggers),
            triggers=triggers,
            evidence=evidence,
        )
