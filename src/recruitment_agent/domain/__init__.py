"""Pure recruitment domain model and external boundary protocols."""

from recruitment_agent.domain.action import ActionItem
from recruitment_agent.domain.application import Application
from recruitment_agent.domain.enums import (
    ActionStatus,
    ActionType,
    ApplicationStatus,
    EventStatus,
    RecruitmentEventType,
)
from recruitment_agent.domain.event import RecruitmentEvent
from recruitment_agent.domain.mail import (
    MailSyncState,
    MailSyncStatus,
    SourceEmail,
    SourceEmailCandidate,
    SourceEmailProcessingStatus,
)

__all__ = [
    "ActionItem",
    "ActionStatus",
    "ActionType",
    "Application",
    "ApplicationStatus",
    "EventStatus",
    "MailSyncState",
    "MailSyncStatus",
    "RecruitmentEvent",
    "RecruitmentEventType",
    "SourceEmail",
    "SourceEmailCandidate",
    "SourceEmailProcessingStatus",
]
