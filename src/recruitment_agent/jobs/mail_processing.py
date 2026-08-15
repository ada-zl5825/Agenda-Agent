"""Production composition boundary for Phase 5/6 start and resume operations."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

import httpx

from recruitment_agent.application.calendar_sync import CalendarPlanner, CalendarSyncService
from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.domain_processing import RecruitmentDomainService
from recruitment_agent.application.entity_resolution import (
    RecruitmentEntityResolutionService,
)
from recruitment_agent.application.recruitment_extraction import (
    RecruitmentExtractionService,
)
from recruitment_agent.application.secure_email_processing import (
    SecureEmailPreparationService,
)
from recruitment_agent.application.secure_links import SecureActionLinkService
from recruitment_agent.config import (
    get_link_encryption_settings,
    get_microsoft_settings,
    get_settings,
)
from recruitment_agent.config.settings import get_azure_openai_settings
from recruitment_agent.domain.company_resolution import CompanyResolver
from recruitment_agent.extraction.langchain_azure import (
    create_azure_recruitment_extraction_model,
)
from recruitment_agent.graph.activities import SecureRecruitmentWorkflowActivities
from recruitment_agent.graph.builder import build_recruitment_graph
from recruitment_agent.graph.context import RecruitmentGraphContext
from recruitment_agent.graph.contracts import ReviewDecision
from recruitment_agent.graph.postgres import open_postgres_checkpointer
from recruitment_agent.graph.runner import (
    RecruitmentWorkflowRunner,
    WorkflowInvocationResult,
    WorkflowStartRequest,
)
from recruitment_agent.jobs.runtime_control import read_calendar_write_control
from recruitment_agent.links.azure import azure_link_key_provider
from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService
from recruitment_agent.microsoft.calendar import GraphCalendarClient
from recruitment_agent.microsoft.crypto import AesGcmCipher
from recruitment_agent.microsoft.graph import GraphMailClient
from recruitment_agent.observability.workflow import MetricsWorkflowPersistence
from recruitment_agent.persistence.calendar import SqlAlchemyCalendarSyncStore
from recruitment_agent.persistence.companies import SqlAlchemyCompanyRepository
from recruitment_agent.persistence.company_resolutions import (
    SqlAlchemyCompanyResolutionAuditRepository,
)
from recruitment_agent.persistence.domain_processing import SqlAlchemyRecruitmentDomainStore
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore
from recruitment_agent.persistence.secure_links import SqlAlchemySecureLinkRepository
from recruitment_agent.persistence.session import create_database_engine, create_session_factory
from recruitment_agent.persistence.workflow import SqlAlchemyWorkflowPersistence


@dataclass(frozen=True, slots=True, kw_only=True)
class MailProcessingJobRequest:
    """Provider metadata needed to start one durable processing run."""

    source_email_id: UUID
    processing_run_id: UUID | None = None


async def run_mail_processing_job(
    request: MailProcessingJobRequest,
    *,
    calendar_write_enabled: bool | None = None,
) -> WorkflowInvocationResult:
    """Start one workflow using production adapters and release owned resources."""
    model_settings = get_azure_openai_settings()
    async with _production_workflow_runner(
        calendar_write_enabled=calendar_write_enabled
    ) as runner:
        return await runner.start(
            WorkflowStartRequest(
                source_email_id=request.source_email_id,
                model_deployment=model_settings.azure_openai_deployment,
                processing_run_id=request.processing_run_id,
            )
        )


async def resume_mail_processing_job(
    *,
    processing_run_id: UUID,
    source_email_id: UUID,
    decision: ReviewDecision,
) -> WorkflowInvocationResult:
    """Resume an interrupted workflow with a server-validated typed decision."""
    # The resume path must honor the same database-backed calendar kill switch
    # as the start path; leaving it unset would re-enable calendar writes.
    calendar_write_enabled = await read_calendar_write_control()
    async with _production_workflow_runner(
        calendar_write_enabled=calendar_write_enabled
    ) as runner:
        return await runner.resume(
            processing_run_id=processing_run_id,
            source_email_id=source_email_id,
            decision=decision,
        )


@asynccontextmanager
async def _production_workflow_runner(
    *,
    calendar_write_enabled: bool | None = None,
) -> AsyncIterator[RecruitmentWorkflowRunner]:
    """Own all network, model, database, and checkpointer resources for one invocation."""
    settings = get_settings()
    microsoft_settings = get_microsoft_settings()
    link_settings = get_link_encryption_settings()
    model_settings = get_azure_openai_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    clock = SystemClock()
    auth_service = MicrosoftAuthorizationService(
        settings=microsoft_settings,
        store=SqlAlchemyMicrosoftAuthStore(session_factory),
        cipher=AesGcmCipher(
            key=microsoft_settings.token_cache_key_bytes,
            key_version=microsoft_settings.token_cache_encryption_key_version,
        ),
        clock=clock,
    )
    timeout = httpx.Timeout(microsoft_settings.graph_request_timeout_seconds)
    try:
        async with (
            httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http_client,
            azure_link_key_provider(link_settings) as key_provider,
            open_postgres_checkpointer(settings.database_url) as checkpointer,
        ):
            model = create_azure_recruitment_extraction_model(model_settings)
            try:
                graph_gateway = GraphMailClient(
                    http_client=http_client,
                    token_provider=auth_service,
                    base_url=str(microsoft_settings.graph_base_url),
                    max_attempts=microsoft_settings.graph_max_retry_attempts,
                    max_retry_delay_seconds=(
                        microsoft_settings.graph_max_retry_delay_seconds
                    ),
                )
                calendar_gateway = GraphCalendarClient(
                    http_client=http_client,
                    token_provider=auth_service,
                    base_url=str(microsoft_settings.graph_base_url),
                    max_attempts=microsoft_settings.graph_max_retry_attempts,
                    max_retry_delay_seconds=(
                        microsoft_settings.graph_max_retry_delay_seconds
                    ),
                )
                link_service = SecureActionLinkService(
                    repository=SqlAlchemySecureLinkRepository(session_factory),
                    encryptor=ActionLinkEncryptor(key_provider),
                )
                extraction_service = RecruitmentExtractionService(model=model)
                activities = SecureRecruitmentWorkflowActivities(
                    preparation_service=SecureEmailPreparationService(
                        gateway=graph_gateway,
                        link_service=link_service,
                    ),
                    extraction_service=extraction_service,
                    entity_resolution_service=RecruitmentEntityResolutionService(
                        extraction_service=extraction_service,
                        company_resolver=CompanyResolver(
                            SqlAlchemyCompanyRepository(session_factory)
                        ),
                        audit_repository=SqlAlchemyCompanyResolutionAuditRepository(
                            session_factory
                        ),
                    ),
                )
                persistence = MetricsWorkflowPersistence(
                    SqlAlchemyWorkflowPersistence(session_factory)
                )
                context = RecruitmentGraphContext(
                    activities=activities,
                    domain=RecruitmentDomainService(
                        SqlAlchemyRecruitmentDomainStore(session_factory)
                    ),
                    persistence=persistence,
                    calendar=CalendarSyncService(
                        store=SqlAlchemyCalendarSyncStore(session_factory),
                        gateway=calendar_gateway,
                        planner=CalendarPlanner(
                            interview_placeholder_minutes=(
                                microsoft_settings.calendar_interview_placeholder_minutes
                            ),
                            assessment_placeholder_minutes=(
                                microsoft_settings.calendar_assessment_placeholder_minutes
                            ),
                        ),
                        clock=clock,
                        # Fail closed: calendar writes require both the deployment
                        # capability and an explicit runtime-control decision.
                        enabled=(
                            microsoft_settings.calendar_sync_enabled
                            and calendar_write_enabled is True
                        ),
                    ),
                    clock=clock,
                )
                yield RecruitmentWorkflowRunner(
                    graph=build_recruitment_graph(checkpointer=checkpointer),
                    context=context,
                )
            finally:
                await model.aclose()
    finally:
        await engine.dispose()
