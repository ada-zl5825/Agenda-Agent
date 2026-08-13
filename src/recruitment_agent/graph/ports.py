"""Typed external ports used by Phase 5 workflow nodes."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from recruitment_agent.domain.ports import Clock
from recruitment_agent.graph.contracts import (
    CalendarPlaceholderResult,
    ExtractionAudit,
    ProcessingRun,
    ProcessingRunStatus,
    ReviewDecision,
    ReviewItem,
    SafePreparedEmail,
    WorkflowExtractionResult,
    WorkflowSourceEmail,
    WorkflowStage,
)


class RecruitmentWorkflowActivities(Protocol):
    async def prepare_email(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        graph_message_id: str,
    ) -> SafePreparedEmail: ...

    async def extract_recruitment_data(
        self,
        prepared: SafePreparedEmail,
    ) -> WorkflowExtractionResult: ...


class WorkflowPersistence(Protocol):
    async def load_source_email(self, source_email_id: UUID) -> WorkflowSourceEmail: ...

    async def start_run(self, run: ProcessingRun) -> None: ...

    async def advance_run(
        self,
        *,
        processing_run_id: UUID,
        stage: WorkflowStage,
        status: ProcessingRunStatus = ProcessingRunStatus.RUNNING,
    ) -> None: ...

    async def record_extraction(
        self,
        audit: ExtractionAudit,
    ) -> WorkflowExtractionResult: ...

    async def open_review(self, item: ReviewItem) -> None: ...

    async def resolve_review(
        self,
        *,
        review_id: UUID,
        decision: ReviewDecision,
        resolved_at: datetime,
    ) -> None: ...

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
    ) -> None: ...


class CalendarSyncPlaceholder(Protocol):
    async def sync(self, *, processing_run_id: UUID) -> CalendarPlaceholderResult: ...


class NoOpCalendarSync:
    """Typed Phase 7 boundary that deliberately performs no calendar action."""

    async def sync(self, *, processing_run_id: UUID) -> CalendarPlaceholderResult:
        del processing_run_id
        return CalendarPlaceholderResult()


class WorkflowClock(Clock, Protocol):
    pass
