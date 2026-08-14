"""Privacy-safe graphical Review contracts."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewQueueItem:
    id: UUID
    source_email_id: UUID
    review_type: str
    reason: str
    created_at: datetime
    company: str | None
    role: str | None
    subject: str | None
    event_type: str | None
    source_time_text: str | None
    orphaned: bool = False


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class ReviewDetail:
    id: UUID
    account_id: UUID
    processing_run_id: UUID
    source_email_id: UUID
    review_type: str
    status: str
    reason: str
    question: str
    allowed_choices: tuple[str, ...]
    version: int
    created_at: datetime
    resolved_at: datetime | None
    resolution: dict[str, object] | None
    run_status: str
    source: Mapping[str, object]
    application: Mapping[str, object]
    extraction: Mapping[str, object]
    validation_findings: tuple[str, ...]
    current_values: Mapping[str, object]
    proposed_values: Mapping[str, object]
    candidates: tuple[Mapping[str, object], ...]
    secure_links: tuple[Mapping[str, object], ...]
    side_effects: tuple[str, ...]
