"""Recruitment application aggregate root."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from recruitment_agent.domain.enums import ApplicationStatus
from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.time import require_aware


@dataclass(slots=True, kw_only=True)
class Application:
    """A candidate's application to a company and role."""

    id: UUID
    company_id: UUID | None
    raw_company_name: str | None
    role_name: str | None
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.raw_company_name is not None and not self.raw_company_name.strip():
            raise DomainValidationError("raw_company_name must be null or non-empty")

        if self.role_name is not None:
            normalized_role = self.role_name.strip()
            self.role_name = normalized_role or None

        require_aware(self.created_at, field_name="created_at")
        require_aware(self.updated_at, field_name="updated_at")
        if self.updated_at < self.created_at:
            msg = "updated_at must not precede created_at"
            raise DomainValidationError(msg)

    @property
    def normalized_identity(self) -> tuple[UUID | None, str | None]:
        """Return an identity keyed by canonical company ID, never a guessed name."""
        role = None
        if self.role_name is not None:
            role = " ".join(self.role_name.casefold().split())
        return self.company_id, role

    @property
    def company_resolved(self) -> bool:
        return self.company_id is not None
