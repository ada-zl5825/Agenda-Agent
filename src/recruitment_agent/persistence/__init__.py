"""PostgreSQL infrastructure adapters."""

from recruitment_agent.persistence.mail import SqlAlchemyMailSyncStore
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore

__all__ = ["SqlAlchemyMailSyncStore", "SqlAlchemyMicrosoftAuthStore"]
