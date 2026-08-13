"""PostgreSQL persistence for processing runs, validated extraction, and reviews."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.domain.mail import SourceEmailProcessingStatus
from recruitment_agent.graph.contracts import (
    ExtractionAudit,
    ProcessingRun,
    ProcessingRunStatus,
    ReviewDecision,
    ReviewItem,
    ReviewStatus,
    WorkflowExtractionResult,
    WorkflowSourceEmail,
    WorkflowStage,
)
from recruitment_agent.persistence.models import (
    LlmExtractionModel,
    ProcessingRunModel,
    ReviewItemModel,
    SourceEmailModel,
)


class SqlAlchemyWorkflowPersistence:
    """Keep workflow audit data authoritative and every retry idempotent."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_source_email(self, source_email_id: UUID) -> WorkflowSourceEmail:
        async with self._session_factory() as session:
            source = await session.get(SourceEmailModel, source_email_id)
        if source is None:
            raise ValueError("source email does not exist")
        return WorkflowSourceEmail(
            id=source.id,
            account_id=source.account_id,
            graph_message_id=source.graph_message_id,
        )

    async def start_run(self, run: ProcessingRun) -> None:
        async with self._session_factory.begin() as session:
            statement = insert(ProcessingRunModel).values(
                id=run.id,
                source_email_id=run.source_email_id,
                graph_thread_id=run.graph_thread_id,
                current_stage=run.current_stage.value,
                status=run.status.value,
                prompt_version=run.prompt_version,
                model_deployment=run.model_deployment,
                started_at=run.started_at,
            )
            await session.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
            stored = await session.get(ProcessingRunModel, run.id)
            if stored is None:
                raise RuntimeError("processing run could not be persisted")
            if (
                stored.source_email_id != run.source_email_id
                or stored.graph_thread_id != run.graph_thread_id
                or stored.prompt_version != run.prompt_version
                or stored.model_deployment != run.model_deployment
            ):
                raise ValueError("processing run identity or version does not match")
            source_result = await session.execute(
                update(SourceEmailModel)
                .where(SourceEmailModel.id == run.source_email_id)
                .values(processing_status=SourceEmailProcessingStatus.PROCESSING.value)
            )
            if getattr(source_result, "rowcount", 0) != 1:
                raise RuntimeError("source email disappeared while starting processing")

    async def advance_run(
        self,
        *,
        processing_run_id: UUID,
        stage: WorkflowStage,
        status: ProcessingRunStatus = ProcessingRunStatus.RUNNING,
    ) -> None:
        async with self._session_factory.begin() as session:
            result = await session.execute(
                update(ProcessingRunModel)
                .where(ProcessingRunModel.id == processing_run_id)
                .values(current_stage=stage.value, status=status.value)
            )
            if getattr(result, "rowcount", 0) != 1:
                raise RuntimeError("processing run does not exist")

    async def record_extraction(
        self,
        audit: ExtractionAudit,
    ) -> WorkflowExtractionResult:
        result = audit.result
        values = result.model_dump(mode="json")
        async with self._session_factory.begin() as session:
            statement = insert(LlmExtractionModel).values(
                id=audit.id,
                processing_run_id=audit.processing_run_id,
                source_email_id=audit.source_email_id,
                extraction=values["extraction"],
                validation=values["validation"],
                company_resolution=values["company"],
                role_resolution=values["role"],
                prompt_version=result.prompt_version,
                company_resolution_audit_id=result.company_resolution_audit_id,
                created_at=audit.created_at,
            )
            await session.execute(
                statement.on_conflict_do_nothing(index_elements=["processing_run_id"])
            )
            stored = await session.scalar(
                select(LlmExtractionModel).where(
                    LlmExtractionModel.processing_run_id == audit.processing_run_id
                )
            )
            if stored is None:
                raise RuntimeError("structured extraction could not be persisted")
            return WorkflowExtractionResult.model_validate(
                {
                    "extraction": stored.extraction,
                    "validation": stored.validation,
                    "prompt_version": stored.prompt_version,
                    "company": stored.company_resolution,
                    "role": stored.role_resolution,
                    "company_resolution_audit_id": stored.company_resolution_audit_id,
                }
            )

    async def open_review(self, item: ReviewItem) -> None:
        async with self._session_factory.begin() as session:
            statement = insert(ReviewItemModel).values(
                id=item.id,
                processing_run_id=item.processing_run_id,
                review_type=item.request.review_type.value,
                reason=item.request.reason,
                question=item.request.question,
                allowed_choices=list(item.request.allowed_choices),
                status=item.status.value,
                version=item.version,
                created_at=item.created_at,
            )
            await session.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
            stored = await session.get(ReviewItemModel, item.id)
            if stored is None:
                raise RuntimeError("review item could not be persisted")
            if (
                stored.processing_run_id != item.processing_run_id
                or stored.review_type != item.request.review_type.value
                or stored.reason != item.request.reason
                or stored.question != item.request.question
                or stored.allowed_choices != list(item.request.allowed_choices)
            ):
                raise ValueError("persisted review request does not match workflow request")

    async def resolve_review(
        self,
        *,
        review_id: UUID,
        decision: ReviewDecision,
        resolved_at: datetime,
    ) -> None:
        resolution = decision.model_dump(mode="json")
        async with self._session_factory.begin() as session:
            result = await session.execute(
                update(ReviewItemModel)
                .where(
                    ReviewItemModel.id == review_id,
                    ReviewItemModel.status == ReviewStatus.OPEN.value,
                    ReviewItemModel.version == decision.expected_version,
                )
                .values(
                    status=ReviewStatus.RESOLVED.value,
                    resolution=resolution,
                    resolved_at=resolved_at,
                    version=ReviewItemModel.version + 1,
                )
            )
            if getattr(result, "rowcount", 0) == 1:
                return
            stored = await session.get(ReviewItemModel, review_id)
            if (
                stored is not None
                and stored.status == ReviewStatus.RESOLVED.value
                and stored.resolution == resolution
            ):
                return
            raise ValueError("review is stale, closed, or resolved differently")

    async def finalize_run(
        self,
        *,
        processing_run_id: UUID,
        source_email_id: UUID,
        stage: WorkflowStage,
        status: ProcessingRunStatus,
        finished_at: datetime,
        error_code: str | None = None,
        error_detail_sanitized: str | None = None,
    ) -> None:
        if status not in {
            ProcessingRunStatus.COMPLETED,
            ProcessingRunStatus.IGNORED,
            ProcessingRunStatus.FAILED,
        }:
            raise ValueError("final processing status is invalid")
        email_status = {
            ProcessingRunStatus.COMPLETED: SourceEmailProcessingStatus.PROCESSED,
            ProcessingRunStatus.IGNORED: SourceEmailProcessingStatus.IGNORED,
            ProcessingRunStatus.FAILED: SourceEmailProcessingStatus.FAILED,
        }[status]
        async with self._session_factory.begin() as session:
            await session.execute(
                update(ProcessingRunModel)
                .where(ProcessingRunModel.id == processing_run_id)
                .values(
                    current_stage=stage.value,
                    status=status.value,
                    finished_at=finished_at,
                    error_code=error_code,
                    error_detail_sanitized=error_detail_sanitized,
                )
            )
            await session.execute(
                update(SourceEmailModel)
                .where(SourceEmailModel.id == source_email_id)
                .values(processing_status=email_status.value)
            )
