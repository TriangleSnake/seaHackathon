from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.detectors.llm import LLMClassification, LLMDetector, binary_decision
from app.domain.models import Evidence
from app.gateways.openai import OpenAIMessageClassifier


class FakeClassifier:
    async def classify(self, messages: list[str], threshold: float) -> LLMClassification:
        assert messages == ["請到外部頁面補填付款資料"]
        assert threshold == 0.6
        return LLMClassification(
            suspicious=True,
            raw_result={"label": "suspicious", "logprobs": [{"token": "suspicious", "logprob": -0.01}]},
        )


def test_llm_detector_preserves_raw_classifier_output() -> None:
    item = Evidence(
        id="MSG-0903",
        source="environment",
        type="message",
        data={"text": "請到外部頁面補填付款資料"},
    )
    detector = LLMDetector(FakeClassifier(), threshold=0.6)

    triggers = asyncio.run(detector.detect([item]))

    assert triggers[0].detector == "llm_classifier"
    assert triggers[0].raw_result["label"] == "suspicious"
    assert triggers[0].evidence_refs == ["MSG-0903"]


def test_binary_decision_accepts_true_above_threshold() -> None:
    decision = binary_decision({"true": -0.1053605, "false": -2.3025851}, 0.6)

    assert decision.suspicious is True
    assert round(decision.raw_result["probabilities"]["true"], 3) == 0.9


def test_binary_decision_abstains_below_threshold() -> None:
    decision = binary_decision({"true": -0.5978370, "false": -0.7985077}, 0.6)

    assert decision.suspicious is False
    assert decision.raw_result["decision"] == "abstain"


def test_binary_decision_abstains_when_candidate_is_missing() -> None:
    decision = binary_decision({"true": -0.01}, 0.6)

    assert decision.suspicious is False
    assert decision.raw_result["decision"] == "abstain"
    assert decision.raw_result["reason"] == "missing_binary_candidate"


def test_openai_classifier_requests_one_token_and_compares_candidates() -> None:
    captured: dict = {}

    class FakeResponses:
        async def create(self, **kwargs):
            captured.update(kwargs)
            true_candidate = SimpleNamespace(
                token="true",
                logprob=-0.2231436,
                top_logprobs=[SimpleNamespace(token="false", logprob=-1.609438)],
            )
            content = SimpleNamespace(logprobs=[true_candidate])
            return SimpleNamespace(
                output_text="true",
                output=[SimpleNamespace(content=[content])],
                model="test-model",
                id="resp-test",
            )

    classifier = OpenAIMessageClassifier.__new__(OpenAIMessageClassifier)
    classifier.client = SimpleNamespace(responses=FakeResponses())
    classifier.model = "test-model"
    result = asyncio.run(classifier.classify(["請在站外驗證付款資料"], 0.6))

    assert captured["max_output_tokens"] == 1
    assert captured["top_logprobs"] == 5
    assert captured["include"] == ["message.output_text.logprobs"]
    assert result.suspicious is True
    assert round(result.raw_result["probabilities"]["true"], 2) == 0.8


def test_openai_classifier_abstains_on_non_boolean_output() -> None:
    class FakeResponses:
        async def create(self, **kwargs):
            true_candidate = SimpleNamespace(
                token="true",
                logprob=-0.1053605,
                top_logprobs=[SimpleNamespace(token="false", logprob=-2.3025851)],
            )
            return SimpleNamespace(
                output_text="maybe",
                output=[SimpleNamespace(content=[SimpleNamespace(logprobs=[true_candidate])])],
                model="test-model",
                id="resp-test",
            )

    classifier = OpenAIMessageClassifier.__new__(OpenAIMessageClassifier)
    classifier.client = SimpleNamespace(responses=FakeResponses())
    classifier.model = "test-model"
    result = asyncio.run(classifier.classify(["測試訊息"], 0.6))

    assert result.suspicious is False
    assert result.raw_result["decision"] == "abstain"
    assert result.raw_result["reason"] == "non_boolean_output"
