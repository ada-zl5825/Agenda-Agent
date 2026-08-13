"""Phase 4.5 application service for deterministic company and role resolution."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from recruitment_agent.application.secure_email_processing import SecurePreparedEmail
from recruitment_agent.domain.company import CompanyResolution, CompanyResolutionAudit
from recruitment_agent.domain.company_resolution import CompanyResolver
from recruitment_agent.domain.repositories import CompanyResolutionAuditRepository
from recruitment_agent.domain.role import NormalizedRole, RoleNormalizer
from recruitment_agent.extraction.models import (
    ExtractionValidationStatus,
    RecruitmentExtractionOutcome,
)


class PhaseFourExtractionService(Protocol):
    async def extract(self, prepared: SecurePreparedEmail) -> RecruitmentExtractionOutcome: ...


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class RecruitmentEntityResolutionOutcome:
    """Phase 4 evidence plus an optional audited Phase 4.5 resolution."""

    extraction: RecruitmentExtractionOutcome
    company: CompanyResolution | None
    role: NormalizedRole | None
    audit_id: UUID | None

    @property
    def needs_company_review(self) -> bool:
        return self.company is not None and self.company.company_id is None

    def __repr__(self) -> str:
        company_status = None if self.company is None else self.company.status.value
        return (
            "RecruitmentEntityResolutionOutcome("
            f"validation={self.extraction.validation.status.value!r}, "
            f"company_status={company_status!r}, "
            f"audited={self.audit_id is not None})"
        )


class RecruitmentEntityResolutionService:
    """Accept validated Phase 4 evidence and persist a deterministic audit result."""

    def __init__(
        self,
        *,
        extraction_service: PhaseFourExtractionService,
        company_resolver: CompanyResolver,
        audit_repository: CompanyResolutionAuditRepository,
        role_normalizer: RoleNormalizer | None = None,
    ) -> None:
        self._extraction_service = extraction_service
        self._company_resolver = company_resolver
        self._audit_repository = audit_repository
        self._role_normalizer = role_normalizer or RoleNormalizer()

    async def extract_and_resolve(
        self,
        prepared: SecurePreparedEmail,
    ) -> RecruitmentEntityResolutionOutcome:
        extraction = await self._extraction_service.extract(prepared)
        return await self.resolve_extraction(
            extraction,
            source_email_id=prepared.normalized.source_email_id,
            sender_domain=prepared.normalized.sender_domain,
        )

    async def resolve_extraction(
        self,
        extraction: RecruitmentExtractionOutcome,
        *,
        source_email_id: UUID,
        sender_domain: str | None,
    ) -> RecruitmentEntityResolutionOutcome:
        """Resolve validated extraction evidence without requiring transient email content."""
        if (
            extraction.validation.status is ExtractionValidationStatus.INVALID
            or not extraction.extraction.relevant
        ):
            return RecruitmentEntityResolutionOutcome(
                extraction=extraction,
                company=None,
                role=None,
                audit_id=None,
            )

        company = await self._company_resolver.resolve(
            company_raw=extraction.extraction.company_raw,
            sender_domain=sender_domain,
        )
        role = self._role_normalizer.normalize(extraction.extraction.role_raw)
        audit = CompanyResolutionAudit.create(
            source_email_id=source_email_id,
            sender_domain=sender_domain,
            resolution=company,
            role=role,
        )
        await self._audit_repository.add(audit)
        return RecruitmentEntityResolutionOutcome(
            extraction=extraction,
            company=company,
            role=role,
            audit_id=audit.id,
        )
