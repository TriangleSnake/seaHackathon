from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class DetectionPolicy(StrictPolicyModel):
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    default_checks: tuple[DetectorType, ...]
    rule_based: RuleBasedPolicy
    anomaly: AnomalyPolicy
    llm_classifier: LLMClassifierPolicy

    @field_validator("default_checks")
    @classmethod
    def unique_default_checks(
        cls, values: tuple[DetectorType, ...]
    ) -> tuple[DetectorType, ...]:
        if len(values) != len(set(values)):
            raise ValueError("default_checks must be unique")
        return values
