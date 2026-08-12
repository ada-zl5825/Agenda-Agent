"""User action item entity."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from recruitment_agent.domain.enums import ActionStatus, ActionType
from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.time import require_aware, require_optional_aware


@dataclass(slots=True, kw_only=True)
class ActionItem:
    """A deterministic task derived from recruitment evidence."""

    id: UUID
    application_id: UUID
    source_email_id: UUID
    type: ActionType
    title: str
    status: ActionStatus
    created_at: datetime
    updated_at: datetime
    due_at: datetime | None = None
    secure_link_id: UUID | None = None

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            msg = "title must not be empty"
            raise DomainValidationError(msg)

        require_optional_aware(self.due_at, field_name="due_at")
        require_aware(self.created_at, field_name="created_at")
        require_aware(self.updated_at, field_name="updated_at")
        if self.updated_at < self.created_at:
            msg = "updated_at must not precede created_at"
            raise DomainValidationError(msg)
