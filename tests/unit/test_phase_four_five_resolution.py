"""Phase 4 to Phase 4.5 company-resolution integration tests."""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from recruitment_agent.application.entity_resolution import (
    RecruitmentEntityResolutionService,
)
from recruitment_agent.application.recruitment_extraction import RecruitmentExtractionService
from recruitment_agent.application.secure_email_processing import SecurePreparedEmail
from recruitment_agent.domain.company import (
    Company,
    CompanyResolutionAudit,
    CompanyResolutionMatch,
    CompanyResolutionMethod,
    CompanyResolutionStatus,
    CompanySeed,
    normalize_company_name,
)
from recruitment_agent.domain.company_resolution import CompanyResolver
from recruitment_agent.domain.role import RoleFamily
from recruitment_agent.email.models import NormalizedEmail, PrefilterDecision, PrefilterResult
from recruitment_agent.extraction.models import (
    ExtractionValidationStatus,
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)
from recruitment_agent.links.models import ActionLinkType, EncryptedActionUrl, SecureLink
from recruitment_agent.privacy.models import SanitizedContent

SOURCE_EMAIL_ID = UUID("00000000-0000-0000-0000-000000000451")
NIMBUS_ID = UUID("00000000-0000-0000-0000-000000000452")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000453")


def _fixture(name: str) -> dict[str, object]:
    return json.loads(
        Path(f"tests/fixtures/extraction/{name}.json").read_text(encoding="utf-8")
    )


def _prepared(fixture: dict[str, object], *, sender_domain: str) -> SecurePreparedEmail:
    allowed_link_refs = tuple(str(value) for value in fixture["allowed_link_refs"])
    links = tuple(
        SecureLink(
            id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
            source_email_id=SOURCE_EMAIL_ID,
            ref=ref,
            link_type=ActionLinkType.ASSESSMENT,
            domain="assessment.example.test",
            encrypted_url=EncryptedActionUrl(
                ciphertext=b"encrypted-only",
                nonce=b"nonce-value12",
                key_version="v1",
            ),
            display_text="assessment",
            created_at=datetime.fromisoformat(str(fixture["received_at"])),
        )
        for index, ref in enumerate(allowed_link_refs, start=1)
    )
    return SecurePreparedEmail(
        normalized=NormalizedEmail(
            source_email_id=SOURCE_EMAIL_ID,
            graph_message_id="phase-4-5-message",
            internet_message_id=None,
            subject="Recruitment update",
            sender_name="Recruitment team",
            sender_address=f"recruitment@{sender_domain}",
            sender_domain=sender_domain,
            outer_sender_name=None,
            outer_sender_address=None,
            outer_sender_domain=None,
            received_at=datetime.fromisoformat(str(fixture["received_at"])),
            body_text="short-lived raw content",
            outlook_web_link=None,
            has_attachments=False,
            is_forwarded=False,
        ),
        secure_links=links,
        sanitized=SanitizedContent(
            text=str(fixture["sanitized_text"]),
            redaction_counts={},
        ),
        prefilter=PrefilterResult(
            decision=PrefilterDecision.LIKELY_RECRUITMENT,
            matched_rules=("recruitment",),
        ),
    )


class StaticExtractionModel:
    def __init__(self, extraction: RecruitmentExtraction) -> None:
        self._extraction = extraction

    async def extract(self, request: RecruitmentExtractionRequest) -> RecruitmentExtraction:
        del request
        return self._extraction


class ExactMatchCompanyRepository:
    def __init__(
        self,
        *,
        aliases: dict[str, tuple[CompanyResolutionMatch, ...]] | None = None,
        domains: dict[str, tuple[CompanyResolutionMatch, ...]] | None = None,
    ) -> None:
        self.aliases = aliases or {}
        self.domains = domains or {}

    async def get(self, company_id: UUID) -> Company | None:
        del company_id
        return None

    async def find_by_normalized_canonical_name(
        self,
        normalized_name: str,
    ) -> Sequence[CompanyResolutionMatch]:
        del normalized_name
        return ()

    async def find_by_normalized_alias(
        self,
        normalized_alias: str,
    ) -> Sequence[CompanyResolutionMatch]:
        return self.aliases.get(normalized_alias, ())

    async def find_by_domain(self, domain: str) -> Sequence[CompanyResolutionMatch]:
        return self.domains.get(domain, ())

    async def upsert_seed(self, seed: CompanySeed) -> Company:
        del seed
        raise AssertionError("resolution must not create a company")


class InMemoryResolutionAuditRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, CompanyResolutionAudit] = {}

    async def add(self, audit: CompanyResolutionAudit) -> None:
        self.records.setdefault(audit.id, audit)


def _service(
    *,
    fixture: dict[str, object],
    repository: ExactMatchCompanyRepository,
    audits: InMemoryResolutionAuditRepository,
    extraction: RecruitmentExtraction | None = None,
) -> RecruitmentEntityResolutionService:
    model_output = extraction or RecruitmentExtraction.model_validate(fixture["response"])
    return RecruitmentEntityResolutionService(
        extraction_service=RecruitmentExtractionService(
            model=StaticExtractionModel(model_output)
        ),
        company_resolver=CompanyResolver(repository),
        audit_repository=audits,
    )


@pytest.mark.asyncio
async def test_valid_phase_four_output_is_resolved_normalized_and_audited() -> None:
    fixture = _fixture("assessment")
    match = CompanyResolutionMatch(
        company_id=NIMBUS_ID,
        matched_value="nimbus labs",
        confidence=0.96,
    )
    repository = ExactMatchCompanyRepository(
        aliases={normalize_company_name("Nimbus Labs"): (match,)}
    )
    audits = InMemoryResolutionAuditRepository()
    service = _service(fixture=fixture, repository=repository, audits=audits)

    outcome = await service.extract_and_resolve(
        _prepared(fixture, sender_domain="nimbus.example")
    )

    assert outcome.extraction.validation.status is ExtractionValidationStatus.VALID
    assert outcome.company is not None
    assert outcome.company.company_id == NIMBUS_ID
    assert outcome.company.method is CompanyResolutionMethod.ALIAS_EXACT
    assert outcome.company.raw_company_name == "Nimbus Labs"
    assert outcome.company.confidence == 0.96
    assert outcome.role is not None
    assert outcome.role.raw_name == "Graduate Engineer"
    assert outcome.role.normalized_name == "graduate engineer"
    assert outcome.role.family is RoleFamily.SOFTWARE_ENGINEERING
    assert outcome.audit_id in audits.records
    assert not outcome.needs_company_review
    assert "Nimbus Labs" not in repr(outcome)


@pytest.mark.asyncio
async def test_conflicting_company_signals_are_ambiguous_and_retry_idempotent() -> None:
    fixture = _fixture("assessment")
    repository = ExactMatchCompanyRepository(
        aliases={
            "nimbus labs": (
                CompanyResolutionMatch(
                    company_id=NIMBUS_ID,
                    matched_value="nimbus labs",
                    confidence=0.96,
                ),
            )
        },
        domains={
            "other.example": (
                CompanyResolutionMatch(
                    company_id=OTHER_ID,
                    matched_value="other.example",
                    confidence=1.0,
                ),
            )
        },
    )
    audits = InMemoryResolutionAuditRepository()
    service = _service(fixture=fixture, repository=repository, audits=audits)
    prepared = _prepared(fixture, sender_domain="other.example")

    first = await service.extract_and_resolve(prepared)
    second = await service.extract_and_resolve(prepared)

    assert first.company is not None
    assert first.company.status is CompanyResolutionStatus.AMBIGUOUS
    assert set(first.company.candidate_company_ids) == {NIMBUS_ID, OTHER_ID}
    assert first.needs_company_review
    assert first.audit_id == second.audit_id
    assert len(audits.records) == 1


@pytest.mark.asyncio
async def test_needs_review_extraction_still_records_deterministic_entity_evidence() -> None:
    fixture = _fixture("interview_without_timezone")
    repository = ExactMatchCompanyRepository(
        aliases={
            "contoso": (
                CompanyResolutionMatch(
                    company_id=NIMBUS_ID,
                    matched_value="contoso",
                    confidence=1.0,
                ),
            )
        }
    )
    audits = InMemoryResolutionAuditRepository()

    outcome = await _service(
        fixture=fixture,
        repository=repository,
        audits=audits,
    ).extract_and_resolve(_prepared(fixture, sender_domain="contoso.example"))

    assert outcome.extraction.validation.status is ExtractionValidationStatus.NEEDS_REVIEW
    assert outcome.company is not None
    assert outcome.company.company_id == NIMBUS_ID
    assert outcome.audit_id in audits.records


@pytest.mark.asyncio
async def test_invalid_phase_four_output_is_not_resolved_or_persisted() -> None:
    fixture = _fixture("assessment")
    invalid = RecruitmentExtraction.model_validate(fixture["response"]).model_copy(
        update={"company_raw": "Invented Corp"}
    )
    repository = ExactMatchCompanyRepository()
    audits = InMemoryResolutionAuditRepository()

    outcome = await _service(
        fixture=fixture,
        repository=repository,
        audits=audits,
        extraction=invalid,
    ).extract_and_resolve(_prepared(fixture, sender_domain="nimbus.example"))

    assert outcome.extraction.validation.status is ExtractionValidationStatus.INVALID
    assert outcome.company is None
    assert outcome.role is None
    assert outcome.audit_id is None
    assert audits.records == {}
