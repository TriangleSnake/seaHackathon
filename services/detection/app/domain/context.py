from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.models import Evidence, Subject


@dataclass(frozen=True)
class DetectionContext:
    subject: Subject
    account_ids: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    as_of: datetime | None = None
    # Context may inform the target-message classifier, but never triggers rules.
    conversation_context: list[Evidence] = field(default_factory=list)
