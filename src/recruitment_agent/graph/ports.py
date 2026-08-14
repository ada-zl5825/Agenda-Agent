"""Typed external ports used by Phase 5/6 workflow nodes."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from recruitment_agent.calendar.models import CalendarSyncRequest, CalendarSyncResult
from recruitment_agent.domain.ports import Clock
from recruitment_agent.domain.processing import (
    ApplicationResolution,
    DomainMutationResult,
    DomainTransitionPlan,
    EventResolution,
    RecruitmentEvidence,
)
from recruitment_agent.graph.contracts import (
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


class RecruitmentDomainActivities(Protocol):
    async def resolve_application(
        self,
        evidence: RecruitmentEvidence,
        *,
        selected_application_id: UUID | None = None,
        force_create: bool = False,
    ) -> ApplicationResolution: ...

    async def resolve_event(
        self,
        evidence: RecruitmentEvidence,
        application: ApplicationResolution,
        *,
        selected_event_id: UUID | None = None,
        treat_as_new: bool = False,
    ) -> EventResolution: ...

    def plan_transition(
        self,
        evidence: RecruitmentEvidence,
        application: ApplicationResolution,
        event: EventResolution,
    ) -> DomainTransitionPlan: ...

    async def persist(self, plan: DomainTransitionPlan) -> DomainMutationResult: ...


class WorkflowPersistence(Protocol):
    async def load_source_email(self, source_email_id: UUID) -> WorkflowSourceEmail: ...

    async def start_run(self, run: ProcessingRun) -> None: ...

    async def get_run_status(
        self,
        processing_run_id: UUID,
    ) -> ProcessingRunStatus | None: ...

    async def mark_source_needs_review(self, source_email_id: UUID) -> None: ...

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


class CalendarSync(Protocol):
    async def sync(self, request: CalendarSyncRequest) -> CalendarSyncResult: ...


class DisabledCalendarSync:
    """Explicit feature-flag boundary used until Calendar consent is complete."""

    async def sync(self, request: CalendarSyncRequest) -> CalendarSyncResult:
        del request
        from recruitment_agent.calendar.models import CalendarSyncOperation

        return CalendarSyncResult(
            operation=CalendarSyncOperation.DISABLED,
            reason="calendar_sync_disabled",
        )


NoOpCalendarSync = DisabledCalendarSync


class WorkflowClock(Clock, Protocol):
    pass
