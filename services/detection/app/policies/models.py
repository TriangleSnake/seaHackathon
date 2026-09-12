from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models import DetectorType


class StrictPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleBasedPolicy(StrictPolicyModel):
    active_report_statuses: tuple[str, ...]
    chat_request_phrases: tuple[str, ...]
    chat_negations: tuple[str, ...]
    risk_domain_suffixes: tuple[str, ...]
    sensitive_security_events: tuple[str, ...]
    access_window_minutes: int = Field(gt=0)
    reused_image_min_products: int = Field(ge=2)
    delivery_claim_terms: tuple[str, ...]


class AnomalyPolicy(StrictPolicyModel):
    payment_instruments_per_hour: int = Field(ge=2)
    login_countries_per_day: int = Field(ge=2)
    login_devices_per_day: int = Field(ge=2)
    messages_per_hour: int = Field(gt=0)
    listings_per_hour: int = Field(gt=0)
    disputes_per_week: int = Field(gt=0)


class LLMClassifierPolicy(StrictPolicyModel):
    confidence_threshold: float = Field(ge=0.5, le=1)


class DetectorComponentPolicy(StrictPolicyModel):
    id: str = Field(min_length=1)
    type: DetectorType
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    enabled: bool = True
    failure_mode: Literal["continue", "fail"] = "continue"
    config: dict[str, Any] = Field(default_factory=dict)


class DetectionPolicy(StrictPolicyModel):
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    default_checks: tuple[DetectorType, ...]
    rule_based: RuleBasedPolicy
    anomaly: AnomalyPolicy
    llm_classifier: LLMClassifierPolicy
    components: tuple[DetectorComponentPolicy, ...] = ()

    @field_validator("default_checks")
    @classmethod
    def unique_default_checks(
        cls, values: tuple[DetectorType, ...]
    ) -> tuple[DetectorType, ...]:
        if len(values) != len(set(values)):
            raise ValueError("default_checks must be unique")
        return values

    @field_validator("components")
    @classmethod
    def unique_component_ids(cls, values: tuple[DetectorComponentPolicy, ...]) -> tuple[DetectorComponentPolicy, ...]:
        ids = [item.id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("component ids must be unique")
        return values

    @model_validator(mode="after")
    def validate_builtin_component_configs(self) -> "DetectionPolicy":
        policy_models = {
            "rule_based": RuleBasedPolicy,
            "anomaly": AnomalyPolicy,
            "llm_classifier": LLMClassifierPolicy,
        }
        defaults = {
            "rule_based": self.rule_based,
            "anomaly": self.anomaly,
            "llm_classifier": self.llm_classifier,
        }
        for component in self.components:
            model = policy_models.get(component.type)
            if model is None:
                continue
            merged = {**defaults[component.type].model_dump(), **component.config}
            model.model_validate(merged)
        return self
