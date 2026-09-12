from app.domain import (
    DefenseVersionSnapshot,
    EvolutionContext,
    PolicyReference,
    PolicyType,
    TriggerType,
)
from app.repositories import InMemoryVersionRepository
from app.runtime import DetectionConfigCapabilityProvider
from app.versioning import VersionManager


class Policies:
    def read_document(self, version):
        assert version == "baseline-v1"
        return {
            "version": version,
            "rule_based": {"chat_request_phrases": ["外部轉帳"]},
            "evaluator_thresholds": "must-not-leak",
        }


def test_runtime_capability_exposes_only_supported_field_and_current_values() -> None:
    base = DefenseVersionSnapshot(
        version="DV-001",
        status="active",
        policies=(PolicyReference(PolicyType.DETECTION, "baseline-v1"),),
        created_at="2026-09-12T00:00:00+00:00",
    )
    provider = DetectionConfigCapabilityProvider(
        Policies(), VersionManager(InMemoryVersionRepository([base]))
    )
    context = EvolutionContext(
        trigger_type=TriggerType.NEW_SPEC_READY,
        trigger_context={},
        current_defense_version="DV-001",
        system_performance={},
    )

    result = provider(context)

    detection = result["detection"]
    assert detection["current_policy_version"] == "baseline-v1"
    field = detection["configurable_fields"][0]
    assert field["path"] == "rule_based.chat_request_phrases"
    assert field["operations"] == ["append_unique", "remove"]
    assert field["required_signals"] == ["message.text"]
    assert field["current_values"] == ["外部轉帳"]
    assert detection["config_builder_scope"]["supports_compound_conditions"] is False
    assert detection["config_builder_scope"]["code_builder_available"] is False
    assert "threshold" not in str(result).lower()
