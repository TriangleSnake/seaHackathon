from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.detectors.llm import LLMClassification, binary_decision


class OpenAIMessageClassifier:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def classify(self, messages: list[str], threshold: float) -> LLMClassification:
        response = await self.client.responses.create(
            model=self.model,
            instructions=(
                "Classify ecommerce chat as suspicious or benign. Reply with exactly "
                "one lowercase boolean token: true or false. True means the sender "
                "requests off-platform payment, credential/payment-data entry, fake "
                "verification, or urgent contact outside the marketplace. Warnings that "
                "tell users not to do those actions are false."
            ),
            input="\n".join(messages),
            include=["message.output_text.logprobs"],
            top_logprobs=5,
            max_output_tokens=1,
            store=False,
        )
        candidate_logprobs: dict[str, float] = {}
        for output in response.output:
            for content in getattr(output, "content", []):
                token_positions = getattr(content, "logprobs", []) or []
                if not token_positions:
                    continue
                first = token_positions[0]
                candidates = [first, *(getattr(first, "top_logprobs", []) or [])]
                for candidate in candidates:
                    token = str(candidate.token).strip().lower()
                    if token in {"true", "false"}:
                        candidate_logprobs[token] = max(
                            float(candidate.logprob),
                            candidate_logprobs.get(token, float("-inf")),
                        )

        output = response.output_text.strip().lower()
        decision = binary_decision(candidate_logprobs, threshold)
        if output not in {"true", "false"}:
            decision = LLMClassification(
                suspicious=False,
                raw_result={
                    **decision.raw_result,
                    "decision": "abstain",
                    "reason": "non_boolean_output",
                },
            )
        elif output == "false" and decision.suspicious:
            decision = LLMClassification(
                suspicious=False,
                raw_result={
                    **decision.raw_result,
                    "decision": "abstain",
                    "reason": "output_candidate_mismatch",
                },
            )
        return LLMClassification(
            suspicious=decision.suspicious,
            raw_result={
                **decision.raw_result,
                "output": output,
                "model": response.model,
                "response_id": response.id,
            },
        )
