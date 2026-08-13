import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from testcontainers.community.postgres import PostgresContainer

from recruitment_agent.application.domain_processing import RecruitmentDomainService
from recruitment_agent.domain.mail import SourceEmailProcessingStatus
from recruitment_agent.extraction.models import (
    ExtractionIssueCode,
    ExtractionIssueSeverity,
    ExtractionValidationIssue,
    ExtractionValidationResult,
    ExtractionValidationStatus,
    RecruitmentExtraction,
)
from recruitment_agent.graph.builder import build_recruitment_graph
from recruitment_agent.graph.context import RecruitmentGraphContext
from recruitment_agent.graph.contracts import (
    CompanyResolutionEvidence,
    ProcessingRunStatus,
    ReviewDecision,
    RoleResolutionEvidence,
    SafePreparedEmail,
    WorkflowExtractionResult,
    WorkflowPrefilterDecision,
)
from recruitment_agent.graph.ports import NoOpCalendarSync
from recruitment_agent.graph.postgres import open_postgres_checkpointer
from recruitment_agent.graph.runner import RecruitmentWorkflowRunner, WorkflowStartRequest
from recruitment_agent.persistence.domain_processing import SqlAlchemyRecruitmentDomainStore
from recruitment_agent.persistence.models import (
    LlmExtractionModel,
    MicrosoftConnectionModel,
    ProcessingRunModel,
    ReviewItemModel,
    SourceEmailModel,
)
from recruitment_agent.persistence.session import create_database_engine, create_session_factory
from recruitment_agent.persistence.workflow import SqlAlchemyWorkflowPersistence

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 on a Docker-enabled host",
    ),
]

INTERVIEW_FIXTURE = json.loads(
    Path("tests/fixtures/extraction/interview_without_timezone.json").read_text(
        encoding="utf-8"
    )
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, 18, tzinfo=UTC)


class StaticActivities:
    def __init__(
        self,
        prepared: SafePreparedEmail,
        result: WorkflowExtractionResult,
    ) -> None:
        self._prepared = prepared
        self._result = result

    async def prepare_email(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        graph_message_id: str,
    ) -> SafePreparedEmail:
        del account_id, source_email_id, graph_message_id
        return self._prepared

    async def extract_recruitment_data(
        self,
        prepared: SafePreparedEmail,
    ) -> WorkflowExtractionResult:
        assert prepared == self._prepared
        return self._result


@pytest.mark.asyncio
async def test_postgres_checkpoint_interrupt_survives_reconstruction() -> None:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "head")

        engine = create_database_engine(database_url)
        session_factory = create_session_factory(engine)
        persistence = SqlAlchemyWorkflowPersistence(session_factory)
        account_id = uuid4()
        source_email_id = uuid4()
        processing_run_id = uuid4()
        company_id = uuid4()
        received_at = datetime(2026, 8, 13, 9, tzinfo=UTC)
        async with session_factory.begin() as session:
            session.add(MicrosoftConnectionModel(id=account_id))
            session.add(
                SourceEmailModel(
                    id=source_email_id,
                    account_id=account_id,
                    graph_message_id="phase-5-postgres",
                    internet_message_id=None,
                    subject="Interview invitation",
                    sender_domain="contoso.example",
                    received_at=received_at,
                    outlook_web_link=None,
                    body_hash=None,
                    has_attachments=False,
                )
            )

        fixture = INTERVIEW_FIXTURE
        extraction = RecruitmentExtraction.model_validate(fixture["response"])
        activities = StaticActivities(
            SafePreparedEmail(
                source_email_id=source_email_id,
                sender_domain="contoso.example",
                received_at=received_at,
                sanitized_text=str(fixture["sanitized_text"]),
                link_refs=(),
                prefilter_decision=WorkflowPrefilterDecision.LIKELY_RECRUITMENT,
            ),
            WorkflowExtractionResult(
                extraction=extraction,
                validation=ExtractionValidationResult(
                    status=ExtractionValidationStatus.NEEDS_REVIEW,
                    issues=(
                        ExtractionValidationIssue(
                            code=ExtractionIssueCode.TIMEZONE_AMBIGUOUS,
                            severity=ExtractionIssueSeverity.REVIEW,
                            field="event_datetime",
                        ),
                    ),
                ),
                prompt_version="recruitment-extraction-v1",
                company=CompanyResolutionEvidence(
                    raw_company_name="Contoso",
                    company_id=company_id,
                    status="resolved",
                    method="alias_exact",
                    confidence=1.0,
                    matched_value="contoso",
                    candidate_company_ids=(),
                ),
                role=RoleResolutionEvidence(
                    raw_name="Data Analyst",
                    normalized_name="data analyst",
                    family="data",
                ),
                company_resolution_audit_id=None,
            ),
        )
        context = RecruitmentGraphContext(
            activities=activities,
            domain=RecruitmentDomainService(
                SqlAlchemyRecruitmentDomainStore(session_factory)
            ),
            persistence=persistence,
            calendar=NoOpCalendarSync(),
            clock=FixedClock(),
        )

        async with open_postgres_checkpointer(database_url) as checkpointer:
            first = await RecruitmentWorkflowRunner(
                graph=build_recruitment_graph(checkpointer=checkpointer),
                context=context,
            ).start(
                WorkflowStartRequest(
                    source_email_id=source_email_id,
                    model_deployment="structured-model",
                    processing_run_id=processing_run_id,
                )
            )
            assert first.interrupted

        async with open_postgres_checkpointer(database_url) as checkpointer:
            resumed = await RecruitmentWorkflowRunner(
                graph=build_recruitment_graph(checkpointer=checkpointer),
                context=context,
            ).resume(
                processing_run_id=processing_run_id,
                source_email_id=source_email_id,
                decision=ReviewDecision(choice="Europe/London"),
            )
            assert resumed.state["status"] == ProcessingRunStatus.COMPLETED.value

        async with session_factory() as session:
            run = await session.get(ProcessingRunModel, processing_run_id)
            source = await session.get(SourceEmailModel, source_email_id)
            review = await session.scalar(
                select(ReviewItemModel).where(
                    ReviewItemModel.processing_run_id == processing_run_id
                )
            )
            extraction_count = await session.scalar(
                select(func.count()).select_from(LlmExtractionModel)
            )
            checkpoint_count = await session.scalar(
                text("SELECT count(*) FROM agent_checkpoint.checkpoints")
            )
        await engine.dispose()

    assert run is not None
    assert run.status == ProcessingRunStatus.COMPLETED.value
    assert source is not None
    assert source.processing_status == SourceEmailProcessingStatus.PROCESSED.value
    assert review is not None
    assert review.status == "resolved"
    assert review.version == 2
    assert extraction_count == 1
    assert checkpoint_count is not None
    assert checkpoint_count > 0
