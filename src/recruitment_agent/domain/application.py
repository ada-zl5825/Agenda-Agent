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
    company_name: str
    role_name: str | None
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        self.company_name = self.company_name.strip()
        if not self.company_name:
            msg = "company_name must not be empty"
            raise DomainValidationError(msg)

        if self.role_name is not None:
            normalized_role = self.role_name.strip()
            self.role_name = normalized_role or None

        require_aware(self.created_at, field_name="created_at")
        require_aware(self.updated_at, field_name="updated_at")
        if self.updated_at < self.created_at:
            msg = "updated_at must not precede created_at"
            raise DomainValidationError(msg)

    @property
    def normalized_identity(self) -> tuple[str, str | None]:
        """Return a deterministic identity key for exact matching."""
        company = " ".join(self.company_name.casefold().split())
        role = None
        if self.role_name is not None:
            role = " ".join(self.role_name.casefold().split())
        return company, role
