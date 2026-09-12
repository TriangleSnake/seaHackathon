"""Manual real-agent smoke: request JSON -> OpenAI synthesis -> validated PatternSpec."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import PatternSynthesisRequest  # noqa: E402
from app.service import PatternSynthesisService  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.synthesizer import OpenAISemanticSynthesizer  # noqa: E402


async def run(path: Path) -> int:
    settings = Settings.from_env()
    if not settings.openai_api_key:
        print("LIVE PATTERN SYNTHESIS NOT RUN: OPENAI_API_KEY is not configured")
        return 2
    request = PatternSynthesisRequest.model_validate_json(path.read_text(encoding="utf-8"))
    synthesizer = OpenAISemanticSynthesizer(
        settings.openai_api_key,
        settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_output_tokens=settings.openai_max_output_tokens,
    )
    try:
        result = await PatternSynthesisService(synthesizer).synthesize(request)
    finally:
        await synthesizer.close()
    print(result.model_dump_json(indent=2))
    print("LIVE PATTERN SYNTHESIS PASS")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path, help="Schema-valid PatternSynthesisRequest JSON")
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(run(arguments.request)))
