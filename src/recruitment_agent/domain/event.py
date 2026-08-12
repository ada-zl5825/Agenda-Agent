"""Recruitment event entity."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from recruitment_agent.domain.enums import EventStatus, RecruitmentEventType
from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.time import require_aware, require_optional_aware


@dataclass(slots=True, kw_only=True)
class RecruitmentEvent:
    """A dated or undated event belonging to an application."""

    id: UUID
    application_id: UUID
    type: RecruitmentEventType
    status: EventStatus
    created_at: datetime
    updated_at: datetime
    round: str | None = None
    starts_at: datetime | None = None
    deadline_at: datetime | None = None
    timezone: str | None = None
    source_datetime_text: str | None = None

    def __post_init__(self) -> None:
        require_optional_aware(self.starts_at, field_name="starts_at")
        require_optional_aware(self.deadline_at, field_name="deadline_at")
        require_aware(self.created_at, field_name="created_at")
        require_aware(self.updated_at, field_name="updated_at")

        if self.updated_at < self.created_at:
            msg = "updated_at must not precede created_at"
            raise DomainValidationError(msg)
        if (self.starts_at is not None or self.deadline_at is not None) and not self.timezone:
            msg = "normalized event datetimes require an explicit timezone"
            raise DomainValidationError(msg)
        if self.round is not None:
            normalized_round = self.round.strip()
            self.round = normalized_round or None
        if self.source_datetime_text is not None:
            source_text = self.source_datetime_text.strip()
            self.source_datetime_text = source_text or None
