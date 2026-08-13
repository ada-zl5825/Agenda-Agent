"""Safe provider-neutral values used by Phase 7 calendar synchronization."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from recruitment_agent.domain.enums import EventStatus, RecruitmentEventType
from recruitment_agent.domain.time import require_aware


class CalendarSyncOperation(StrEnum):
    DISABLED = "disabled"
    SKIPPED = "skipped"
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    REVIEW_REQUIRED = "review_required"


class CalendarSyncResult(BaseModel):
    """Checkpoint-safe result; provider IDs and descriptions stay out of graph state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: CalendarSyncOperation
    reason: str

    @property
    def needs_review(self) -> bool:
        return self.operation is CalendarSyncOperation.REVIEW_REQUIRED


@dataclass(frozen=True, slots=True, kw_only=True)
class CalendarSyncRequest:
    account_id: UUID
    source_email_id: UUID
    recruitment_event_id: UUID | None
    replace_missing_event: bool = False
    skip_update: bool = False


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class CalendarCandidate:
    """Privacy-minimized authoritative read model loaded from domain tables."""

    account_id: UUID
    source_email_id: UUID
    recruitment_event_id: UUID
    application_id: UUID
    application_resolved: bool
    company_display_name: str | None
    role_name: str | None
    event_type: RecruitmentEventType
    event_status: EventStatus
    interview_round: str | None
    starts_at: datetime | None
    deadline_at: datetime | None
    timezone: str | None
    source_datetime_text: str | None
    outlook_web_link: str | None


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class CalendarEventDraft:
    subject: str
    body: str
    starts_at: datetime
    ends_at: datetime
    content_fingerprint: str
    transaction_id: str

    def __post_init__(self) -> None:
        require_aware(self.starts_at, field_name="starts_at")
        require_aware(self.ends_at, field_name="ends_at")
        if self.ends_at <= self.starts_at:
            raise ValueError("calendar event end must be after its start")
        if not self.subject.strip() or not self.body.strip():
            raise ValueError("calendar event content must not be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class CalendarProviderEvent:
    event_id: str

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("provider calendar event ID must not be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class CalendarLinkSnapshot:
    recruitment_event_id: UUID
    account_id: UUID
    provider: str
    calendar_event_id: str
    content_fingerprint: str
    last_synced_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.last_synced_at, field_name="last_synced_at")
