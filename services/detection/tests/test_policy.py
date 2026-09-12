from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.policies.repository import (
    FilePolicyRepository,
    LayeredFilePolicyRepository,
    PolicyNotFoundError,
)


def test_file_policy_repository_loads_versioned_config(tmp_path) -> None:
    config = {
        "version": "test-v1",
        "default_checks": ["rule_based", "anomaly"],
        "rule_based": {
            "active_report_statuses": ["open"],
            "chat_request_phrases": ["外部轉帳"],
            "chat_negations": ["不會"],
            "risk_domain_suffixes": [".invalid"],
            "sensitive_security_events": ["password_reset"],
            "access_window_minutes": 120,
            "reused_image_min_products": 2,
            "delivery_claim_terms": ["未收到"]
        },
        "anomaly": {
            "payment_instruments_per_hour": 2,
            "login_countries_per_day": 3,
            "login_devices_per_day": 4,
            "messages_per_hour": 8,
            "listings_per_hour": 5,
            "disputes_per_week": 2
        },
        "llm_classifier": {"confidence_threshold": 0.6}
    }
    (tmp_path / "test-v1.json").write_text(json.dumps(config))

    policy = FilePolicyRepository(tmp_path).resolve("test-v1")

    assert policy.version == "test-v1"
    assert policy.llm_classifier.confidence_threshold == 0.6


def test_file_policy_repository_rejects_unknown_or_unsafe_versions(tmp_path) -> None:
    repository = FilePolicyRepository(tmp_path)

    with pytest.raises(PolicyNotFoundError):
        repository.resolve("../secret")
    with pytest.raises(PolicyNotFoundError):
        repository.resolve("missing-v1")


def test_bundled_baseline_and_candidate_are_valid_and_immutable() -> None:
    repository = FilePolicyRepository("config/policies")

    baseline = repository.resolve("baseline-v1")
    candidate = repository.resolve("candidate-v1")

    assert baseline.version == "baseline-v1"
    assert candidate.version == "candidate-v1"
    assert baseline.anomaly.listings_per_hour == 5
    assert candidate.anomaly.listings_per_hour == 4
    with pytest.raises(ValidationError):
        candidate.version = "mutated"


def test_layered_repository_reads_baseline_and_runtime_candidate(tmp_path) -> None:
    baseline_dir = tmp_path / "baseline"
    candidate_dir = tmp_path / "candidate"
    baseline_dir.mkdir()
    candidate_dir.mkdir()
    baseline = json.loads(
        open("config/policies/baseline-v1.json", encoding="utf-8").read()
    )
    candidate = dict(baseline)
    candidate["version"] = "DP-CAND-001"
    (baseline_dir / "baseline-v1.json").write_text(json.dumps(baseline))
    (candidate_dir / "DP-CAND-001.json").write_text(json.dumps(candidate))

    repository = LayeredFilePolicyRepository((baseline_dir, candidate_dir))

    assert repository.resolve("baseline-v1").version == "baseline-v1"
    assert repository.resolve("DP-CAND-001").version == "DP-CAND-001"


def test_layered_repository_rejects_duplicate_policy_versions(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    baseline = json.loads(
        open("config/policies/baseline-v1.json", encoding="utf-8").read()
    )
    for root in (first, second):
        (root / "baseline-v1.json").write_text(json.dumps(baseline))

    with pytest.raises(ValueError, match="multiple policy directories"):
        LayeredFilePolicyRepository((first, second)).resolve("baseline-v1")
