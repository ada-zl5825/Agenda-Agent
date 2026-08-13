"""PostgreSQL infrastructure adapters."""

from recruitment_agent.persistence.mail import SqlAlchemyMailSyncStore
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore
from recruitment_agent.persistence.secure_links import SqlAlchemySecureLinkRepository

__all__ = [
    "SqlAlchemyMailSyncStore",
    "SqlAlchemyMicrosoftAuthStore",
    "SqlAlchemySecureLinkRepository",
]
