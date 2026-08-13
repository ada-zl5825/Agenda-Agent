"""Application services coordinate domain rules and external ports."""

from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.email_processing import EmailPreparationService, PreparedEmail
from recruitment_agent.application.mail_sync import MailSyncService
from recruitment_agent.application.secure_email_processing import (
    SecureEmailPreparationService,
    SecurePreparedEmail,
)

__all__ = [
    "EmailPreparationService",
    "MailSyncService",
    "PreparedEmail",
    "SecureEmailPreparationService",
    "SecurePreparedEmail",
    "SystemClock",
]
