from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import Evidence, Subject


@dataclass(frozen=True)
class DetectionContext:
    subject: Subject
    account_ids: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
