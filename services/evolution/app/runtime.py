from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .domain import (
    DETECTION_CHAT_REQUEST_PHRASES_PATH,
    EvolutionContext,
    PolicyType,
)


class PolicyDocumentRepository(Protocol):
    def read_document(self, version: str) -> dict[str, Any]: ...


class BaseVersionReader(Protocol):
    def read_base(self, version: str) -> Any: ...


class DetectionConfigCapabilityProvider:
    """Expose only the real CONFIG surface and current values to the planner."""

    def __init__(
        self,
        policy_repository: PolicyDocumentRepository,
        versions: BaseVersionReader,
        *, code_builder_available: bool = False,
    ) -> None:
        self._policies = policy_repository
        self._versions = versions
        self._code_builder_available = code_builder_available

    def __call__(self, context: EvolutionContext) -> Mapping[str, Any]:
        defense = self._versions.read_base(context.current_defense_version)
        detection_refs = tuple(
            reference
            for reference in defense.policies
            if reference.policy_type is PolicyType.DETECTION
        )
        if len(detection_refs) != 1:
            raise ValueError(
                "Current defense must contain exactly one Detection policy reference"
            )
        policy_ref = detection_refs[0].version
        document = self._policies.read_document(policy_ref)
        rule_based = document.get("rule_based")
        if not isinstance(rule_based, Mapping):
            raise ValueError("Detection policy has no rule_based configuration")
        current_values = rule_based.get("chat_request_phrases")
        if not isinstance(current_values, list) or any(
            not isinstance(value, str) for value in current_values
        ):
            raise ValueError(
                "Detection chat_request_phrases must be a string list"
            )

        capabilities: dict[str, Any] = {
            policy.value: {"kind": "UNSUPPORTED", "configurable_fields": []}
            for policy in PolicyType
        }
        capabilities[PolicyType.DETECTION.value] = {
            "kind": "CONFIG",
            "current_policy_version": policy_ref,
            "runtime_capability": "exact substring matching against message.text",
            "config_builder_scope": {
                "supports_compound_conditions": False,
                "supports_role_or_account_conditions": False,
                "supports_transaction_amount_conditions": False,
                "supports_generic_allowlists": False,
                "supports_custom_trigger_generation": False,
                "unsupported_behavior_resolution": "CODE",
                "code_builder_available": self._code_builder_available,
            },
            "configurable_fields": [
                {
                    "path": DETECTION_CHAT_REQUEST_PHRASES_PATH,
                    "value_type": "string_list",
                    "operations": ["append_unique", "remove"],
                    "required_signals": ["message.text"],
                    "current_values": list(current_values),
                }
            ],
        }
        return capabilities
