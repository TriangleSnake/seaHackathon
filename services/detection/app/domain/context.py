from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.models import Evidence, Subject


@dataclass(frozen=True)
class DetectionContext:
    subject: Subject
    account_ids: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
