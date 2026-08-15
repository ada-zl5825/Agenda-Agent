"""Adapters connecting existing Phase 2-4.5 services to safe graph contracts."""

from uuid import UUID

from recruitment_agent.application.entity_resolution import (
    RecruitmentEntityResolutionService,
)
from recruitment_agent.application.recruitment_extraction import (
    RecruitmentExtractionService,
)
from recruitment_agent.application.secure_email_processing import (
    SecureEmailPreparationService,
)
from recruitment_agent.extraction.models import RecruitmentExtractionRequest
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_VERSION
from recruitment_agent.extraction.usage import consume_extraction_usage
from recruitment_agent.graph.contracts import (
    CompanyResolutionEvidence,
    RoleResolutionEvidence,
    SafePreparedEmail,
    WorkflowExtractionResult,
    WorkflowPrefilterDecision,
)


class SecureRecruitmentWorkflowActivities:
    """Discard transient mail content before returning from the preparation activity."""

    def __init__(
        self,
        *,
        preparation_service: SecureEmailPreparationService,
        extraction_service: RecruitmentExtractionService,
        entity_resolution_service: RecruitmentEntityResolutionService,
    ) -> None:
        self._preparation_service = preparation_service
        self._extraction_service = extraction_service
        self._entity_resolution_service = entity_resolution_service

    async def prepare_email(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        graph_message_id: str,
    ) -> SafePreparedEmail:
        transient = await self._preparation_service.prepare(
            account_id=account_id,
            source_email_id=source_email_id,
            graph_message_id=graph_message_id,
        )
        return SafePreparedEmail(
            source_email_id=source_email_id,
            sender_domain=transient.normalized.sender_domain,
            received_at=transient.normalized.received_at,
            sanitized_text=transient.sanitized.text,
            link_refs=tuple(link.ref for link in transient.secure_links),
            prefilter_decision=WorkflowPrefilterDecision(
                transient.prefilter.decision.value
            ),
        )

    async def extract_recruitment_data(
        self,
        prepared: SafePreparedEmail,
    ) -> WorkflowExtractionResult:
        request = RecruitmentExtractionRequest(
            source_email_id=prepared.source_email_id,
            received_at=prepared.received_at,
            sanitized_text=prepared.sanitized_text,
            allowed_link_refs=prepared.link_refs,
            prompt_version=RECRUITMENT_EXTRACTION_PROMPT_VERSION,
        )
        extraction = await self._extraction_service.extract_request(request)
        usage = consume_extraction_usage()
        resolved = await self._entity_resolution_service.resolve_extraction(
            extraction,
            source_email_id=prepared.source_email_id,
            sender_domain=prepared.sender_domain,
        )
        company = resolved.company
        role = resolved.role
        return WorkflowExtractionResult(
            extraction=resolved.extraction.extraction,
            validation=resolved.extraction.validation,
            prompt_version=resolved.extraction.prompt_version,
            usage=usage,
            company=None
            if company is None
            else CompanyResolutionEvidence(
                raw_company_name=company.raw_company_name,
                company_id=company.company_id,
                status=company.status.value,
                method=company.method.value,
                confidence=company.confidence,
                matched_value=company.matched_value,
                candidate_company_ids=company.candidate_company_ids,
            ),
            role=None
            if role is None
            else RoleResolutionEvidence(
                raw_name=role.raw_name,
                normalized_name=role.normalized_name,
                family=None if role.family is None else role.family.value,
            ),
            company_resolution_audit_id=resolved.audit_id,
        )
