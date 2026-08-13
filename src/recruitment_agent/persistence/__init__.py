"""PostgreSQL infrastructure adapters."""

from recruitment_agent.persistence.companies import SqlAlchemyCompanyRepository
from recruitment_agent.persistence.company_resolutions import (
    SqlAlchemyCompanyResolutionAuditRepository,
)
from recruitment_agent.persistence.mail import SqlAlchemyMailSyncStore
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore
from recruitment_agent.persistence.secure_links import SqlAlchemySecureLinkRepository

__all__ = [
    "SqlAlchemyCompanyRepository",
    "SqlAlchemyCompanyResolutionAuditRepository",
    "SqlAlchemyMailSyncStore",
    "SqlAlchemyMicrosoftAuthStore",
    "SqlAlchemySecureLinkRepository",
]
