"""Pure recruitment domain model and external boundary protocols."""

from recruitment_agent.domain.action import ActionItem
from recruitment_agent.domain.application import Application
from recruitment_agent.domain.company import (
    Company,
    CompanyAlias,
    CompanyDataSource,
    CompanyDomain,
    CompanyEntityType,
    CompanyResolution,
    CompanyResolutionMethod,
    CompanyResolutionStatus,
    CompanyStatus,
    RawCompanyRole,
    normalize_company_name,
)
from recruitment_agent.domain.company_resolution import CompanyResolver
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
    "Company",
    "CompanyAlias",
    "CompanyDataSource",
    "CompanyDomain",
    "CompanyEntityType",
    "CompanyResolution",
    "CompanyResolutionMethod",
    "CompanyResolutionStatus",
    "CompanyResolver",
    "CompanyStatus",
    "EventStatus",
    "MailSyncState",
    "MailSyncStatus",
    "RawCompanyRole",
    "RecruitmentEvent",
    "RecruitmentEventType",
    "SourceEmail",
    "SourceEmailCandidate",
    "SourceEmailProcessingStatus",
    "normalize_company_name",
]
