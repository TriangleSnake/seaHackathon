from __future__ import annotations

from dataclasses import dataclass
import json
from math import exp
from typing import Any, Protocol

from app.domain.models import DetectionTrigger, Evidence
from app.errors import CheckInconclusiveError


@dataclass(frozen=True)
class LLMClassification:
    suspicious: bool
    raw_result: dict[str, Any]


def binary_decision(
    candidate_logprobs: dict[str, float], threshold: float
) -> LLMClassification:
    """Normalize true/false logprobs and apply a conservative decision threshold."""
    if not 0.5 <= threshold <= 1:
        raise ValueError("LLM confidence threshold must be between 0.5 and 1")
    if "true" not in candidate_logprobs or "false" not in candidate_logprobs:
        return LLMClassification(
            suspicious=False,
            raw_result={
                "label": None,
                "candidate_logprobs": candidate_logprobs,
                "probabilities": None,
                "threshold": threshold,
                "decision": "abstain",
                "reason": "missing_binary_candidate",
            },
        )

    true_logprob = candidate_logprobs["true"]
    false_logprob = candidate_logprobs["false"]
    offset = max(true_logprob, false_logprob)
    true_weight = exp(true_logprob - offset)
    false_weight = exp(false_logprob - offset)
    total = true_weight + false_weight
    true_probability = true_weight / total
    false_probability = false_weight / total
    suspicious = true_logprob > false_logprob and true_probability >= threshold
    return LLMClassification(
        suspicious=suspicious,
        raw_result={
            "label": true_logprob > false_logprob,
            "candidate_logprobs": candidate_logprobs,
            "probabilities": {
                "true": true_probability,
                "false": false_probability,
            },
            "threshold": threshold,
            "decision": "trigger" if suspicious else "not_triggered",
        },
    )


class MessageClassifier(Protocol):
    async def classify(self, messages: list[str], threshold: float) -> LLMClassification: ...


class LLMDetector:
    detector_type = "llm_classifier"

    def __init__(self, classifier: MessageClassifier, threshold: float) -> None:
        self.classifier = classifier
        self.threshold = threshold

    async def detect(
        self, evidence: list[Evidence], *, target_message_id: str | None = None,
        background: list[Evidence] | None = None,
    ) -> list[DetectionTrigger]:
        message_evidence = [
            item for item in evidence if item.type == "message" and item.data.get("text")
        ]
        if not message_evidence:
            raise CheckInconclusiveError("llm_classifier: no message text available")
        used_background: list[Evidence] = []
        if target_message_id is not None:
            message_evidence = [item for item in message_evidence if item.id == target_message_id]
            if not message_evidence:
                raise CheckInconclusiveError("llm_classifier: target message has no text")
            used_background = [item for item in background or [] if item.type == "message" and item.data.get("text")]
            def record(item: Evidence) -> dict[str, Any]:
                return {"id": item.id, "sender_account_id": item.data.get("sender_account_id"),
                        "recipient_account_id": item.data.get("recipient_account_id"),
                        "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                        "text": item.data["text"], "urls": item.data.get("urls", [])}
            inputs = [json.dumps({"target_message": record(message_evidence[0]),
                                  "background_messages": [record(item) for item in used_background]}, ensure_ascii=False)]
        else:
            inputs = [str(item.data["text"]) for item in message_evidence]
        classification = await self.classifier.classify(inputs, self.threshold)
        if classification.raw_result.get("decision") == "abstain":
            raise CheckInconclusiveError("llm_classifier: " + str(classification.raw_result.get("reason", "abstain")))
        if not classification.suspicious:
            return []
        return [
            DetectionTrigger(
                type="llm_suspicious_chat",
                detector="llm_classifier",
                rule_id="LLM-CHAT-001",
                reason="The optional binary classifier marked the chat as suspicious.",
                raw_result={**classification.raw_result, **({
                    "target_message_id": target_message_id,
                    "background_message_ids": [item.id for item in used_background],
                } if target_message_id else {})},
                evidence_refs=[item.id for item in message_evidence + used_background],
            )
        ]
