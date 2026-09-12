from __future__ import annotations

import json
from pathlib import Path

from app.contracts import SharedContractValidator
from app.models import InvestigationResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REAL_INVESTIGATION_SAMPLE = (
    REPOSITORY_ROOT
    / "docs"
    / "test-runs"
    / "2026-09-12-investigation-chat-zh-2"
    / "response.json"
)


def test_current_real_investigation_sample_is_contract_compatible() -> None:
    payload = json.loads(REAL_INVESTIGATION_SAMPLE.read_text(encoding="utf-8"))
    SharedContractValidator().investigation_result(payload)
    parsed = InvestigationResult.model_validate(payload)
    assert parsed.case_id == "TEST-CHAT-0901-ZH-2"
    assert parsed.evidence[0].id == "MSG-0901"
