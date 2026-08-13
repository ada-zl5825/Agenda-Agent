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
    CompanyResolutionAudit,
    CompanyResolutionMatch,
    CompanyResolutionMethod,
    CompanyResolutionResult,
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
from recruitment_agent.domain.role import (
    NormalizedRole,
    RoleFamily,
    RoleNormalizer,
    normalize_role_name,
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
    "CompanyResolutionAudit",
    "CompanyResolutionMatch",
    "CompanyResolutionMethod",
    "CompanyResolutionResult",
    "CompanyResolutionStatus",
    "CompanyResolver",
    "CompanyStatus",
    "EventStatus",
    "MailSyncState",
    "MailSyncStatus",
    "NormalizedRole",
    "RawCompanyRole",
    "RecruitmentEvent",
    "RecruitmentEventType",
    "RoleFamily",
    "RoleNormalizer",
    "SourceEmail",
    "SourceEmailCandidate",
    "SourceEmailProcessingStatus",
    "normalize_company_name",
    "normalize_role_name",
]
