"""Branch, interrupt, resume, retry, and privacy tests for Phase 5."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from recruitment_agent.application.domain_processing import RecruitmentDomainService
from recruitment_agent.calendar.models import (
    CalendarSyncOperation,
    CalendarSyncRequest,
    CalendarSyncResult,
)
from recruitment_agent.domain.enums import ApplicationStatus, EventStatus, RecruitmentEventType
from recruitment_agent.domain.ports import Clock
from recruitment_agent.domain.processing import (
    ApplicationSnapshot,
    DomainMutationResult,
    DomainTransitionPlan,
    EventSnapshot,
)
from recruitment_agent.extraction.models import (
    ExtractionIssueCode,
    ExtractionIssueSeverity,
    ExtractionValidationIssue,
    ExtractionValidationResult,
    ExtractionValidationStatus,
    RecruitmentExtraction,
)
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_VERSION
from recruitment_agent.graph.builder import build_recruitment_graph
from recruitment_agent.graph.context import RecruitmentGraphContext
from recruitment_agent.graph.contracts import (
    CompanyResolutionEvidence,
    ExtractionAudit,
    ProcessingRun,
    ProcessingRunStatus,
    ReviewDecision,
    ReviewItem,
    ReviewRequest,
    ReviewStatus,
    ReviewType,
    RoleResolutionEvidence,
    SafePreparedEmail,
    WorkflowExtractionResult,
    WorkflowPrefilterDecision,
    WorkflowSourceEmail,
    WorkflowStage,
    successor_review_id,
)
from recruitment_agent.graph.ports import CalendarSync, NoOpCalendarSync
from recruitment_agent.graph.runner import RecruitmentWorkflowRunner, WorkflowStartRequest

RUN_ID = UUID("00000000-0000-0000-0000-000000000501")
SOURCE_EMAIL_ID = UUID("00000000-0000-0000-0000-000000000502")
ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000503")
COMPANY_ID = UUID("00000000-0000-0000-0000-000000000504")
OTHER_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000505")
APPLICATION_ID = UUID("00000000-0000-0000-0000-000000000506")
OTHER_APPLICATION_ID = UUID("00000000-0000-0000-0000-000000000507")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000508")
OTHER_EVENT_ID = UUID("00000000-0000-0000-0000-000000000509")
NOW = datetime(2026, 8, 13, 18, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class ReviewableCalendarSync:
    def __init__(self) -> None:
        self.requests: list[CalendarSyncRequest] = []

    async def sync(self, request: CalendarSyncRequest) -> CalendarSyncResult:
        self.requests.append(request)
        if request.replace_missing_event:
            return CalendarSyncResult(
                operation=CalendarSyncOperation.CREATED,
                reason="missing_calendar_event_replaced",
            )
        return CalendarSyncResult(
            operation=CalendarSyncOperation.REVIEW_REQUIRED,
            reason="linked_calendar_event_missing",
        )


class FakeActivities:
    def __init__(
        self,
        *,
        prepared: SafePreparedEmail,
        extraction: WorkflowExtractionResult,
        failure: Exception | None = None,
    ) -> None:
        self.prepared = prepared
        self.extraction = extraction
        self.failure = failure
        self.prepare_calls = 0
        self.extract_calls = 0

    async def prepare_email(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        graph_message_id: str,
    ) -> SafePreparedEmail:
        assert account_id == ACCOUNT_ID
        assert source_email_id == SOURCE_EMAIL_ID
        assert graph_message_id == "graph-phase-5"
        self.prepare_calls += 1
        return self.prepared

    async def extract_recruitment_data(
        self,
        prepared: SafePreparedEmail,
    ) -> WorkflowExtractionResult:
        assert prepared == self.prepared
        self.extract_calls += 1
        if self.failure is not None:
            raise self.failure
        return self.extraction


class FakeWorkflowPersistence:
    def __init__(self) -> None:
        self.runs: dict[UUID, ProcessingRun] = {}
        self.stages: list[WorkflowStage] = []
        self.extractions: dict[UUID, WorkflowExtractionResult] = {}
        self.reviews: dict[UUID, ReviewItem] = {}
        self.resolutions: dict[UUID, ReviewDecision] = {}
        self.final_status: ProcessingRunStatus | None = None
        self.error_code: str | None = None
        self.error_detail: str | None = None
        self.stored_run_status: ProcessingRunStatus | None = None
        self.needs_review_marks: list[UUID] = []

    async def load_source_email(self, source_email_id: UUID) -> WorkflowSourceEmail:
        assert source_email_id == SOURCE_EMAIL_ID
        return WorkflowSourceEmail(
            id=SOURCE_EMAIL_ID,
            account_id=ACCOUNT_ID,
            graph_message_id="graph-phase-5",
        )

    async def start_run(self, run: ProcessingRun) -> None:
        self.runs.setdefault(run.id, run)
        self.stages.append(run.current_stage)

    async def get_run_status(
        self,
        processing_run_id: UUID,
    ) -> ProcessingRunStatus | None:
        del processing_run_id
        return self.stored_run_status

    async def mark_source_needs_review(self, source_email_id: UUID) -> None:
        self.needs_review_marks.append(source_email_id)

    async def advance_run(
        self,
        *,
        processing_run_id: UUID,
        stage: WorkflowStage,
        status: ProcessingRunStatus = ProcessingRunStatus.RUNNING,
    ) -> None:
        assert processing_run_id == RUN_ID
        del status
        self.stages.append(stage)

    async def record_extraction(
        self,
        audit: ExtractionAudit,
    ) -> WorkflowExtractionResult:
        return self.extractions.setdefault(audit.processing_run_id, audit.result)

    async def open_review(self, item: ReviewItem) -> ReviewItem:
        existing = self.reviews.get(item.id)
        if existing is not None and existing.status is ReviewStatus.RESOLVED:
            nxt = replace(
                item,
                id=successor_review_id(existing.id, existing.version),
            )
            self.reviews[nxt.id] = nxt
            return nxt
        return self.reviews.setdefault(item.id, item)

    async def resolve_review(
        self,
        *,
        review_id: UUID,
        decision: ReviewDecision,
        resolved_at: datetime,
    ) -> None:
        assert resolved_at == NOW
        existing = self.resolutions.get(review_id)
        if existing is not None and existing != decision:
            raise ValueError("review resolution conflict")
        self.resolutions[review_id] = decision
        item = self.reviews.get(review_id)
        if item is not None:
            self.reviews[review_id] = replace(
                item,
                status=ReviewStatus.RESOLVED,
                version=item.version + 1,
            )

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
        assert processing_run_id == RUN_ID
        assert source_email_id == SOURCE_EMAIL_ID
        assert finished_at == NOW
        self.stages.append(stage)
        self.final_status = status
        self.error_code = error_code
        self.error_detail = error_detail_sanitized


class MismatchedSourcePersistence(FakeWorkflowPersistence):
    async def load_source_email(self, source_email_id: UUID) -> WorkflowSourceEmail:
        assert source_email_id == SOURCE_EMAIL_ID
        return WorkflowSourceEmail(
            id=OTHER_COMPANY_ID,
            account_id=ACCOUNT_ID,
            graph_message_id="different-message",
        )


class FakeDomainStore:
    def __init__(
        self,
        *,
        linked: ApplicationSnapshot | None = None,
        applications: tuple[ApplicationSnapshot, ...] = (),
        events: tuple[EventSnapshot, ...] = (),
    ) -> None:
        self.linked = linked
        self.applications = applications
        self.events = events
        self.plans: list[DomainTransitionPlan] = []

    async def application_for_source_email(
        self,
        source_email_id: UUID,
    ) -> ApplicationSnapshot | None:
        del source_email_id
        return self.linked

    async def find_open_applications(
        self,
        *,
        company_id: UUID,
        role_normalized: str | None,
    ) -> tuple[ApplicationSnapshot, ...]:
        return tuple(
            item
            for item in self.applications
            if item.company_id == company_id
            and (role_normalized is None or item.role_normalized == role_normalized)
        )

    async def find_event_by_fingerprint(
        self,
        *,
        application_id: UUID,
        semantic_fingerprint: str,
    ) -> EventSnapshot | None:
        return next(
            (
                item
                for item in self.events
                if item.application_id == application_id
                and item.semantic_fingerprint == semantic_fingerprint
            ),
            None,
        )

    async def list_active_interviews(
        self,
        application_id: UUID,
    ) -> tuple[EventSnapshot, ...]:
        return tuple(item for item in self.events if item.application_id == application_id)

    async def apply_transition(
        self,
        plan: DomainTransitionPlan,
    ) -> DomainMutationResult:
        self.plans.append(plan)
        if not plan.mutations_allowed:
            return DomainMutationResult(
                application_id=None if plan.create_application else plan.application_id,
                event_id=None,
                action_item_ids=(),
                changed=False,
                no_mutation_reason=plan.no_mutation_reason,
            )
        return DomainMutationResult(
            application_id=plan.application_id,
            event_id=plan.event.event_id,
            action_item_ids=()
            if plan.action_item is None
            else (plan.action_item.id,),
            changed=True,
        )


def _fixture(name: str) -> dict[str, object]:
    return json.loads(
        Path(f"tests/fixtures/extraction/{name}.json").read_text(encoding="utf-8")
    )


def _prepared(
    *,
    prefilter: WorkflowPrefilterDecision = WorkflowPrefilterDecision.LIKELY_RECRUITMENT,
) -> SafePreparedEmail:
    return SafePreparedEmail(
        source_email_id=SOURCE_EMAIL_ID,
        sender_domain="careers.example.test",
        received_at=NOW,
        sanitized_text="Nimbus Labs Graduate Engineer assessment using ACTION_LINK_01.",
        link_refs=("ACTION_LINK_01",),
        prefilter_decision=prefilter,
    )


def _validation(
    status: ExtractionValidationStatus,
    *codes: ExtractionIssueCode,
) -> ExtractionValidationResult:
    return ExtractionValidationResult(
        status=status,
        issues=tuple(
            ExtractionValidationIssue(
                code=code,
                severity=ExtractionIssueSeverity.REVIEW
                if status is ExtractionValidationStatus.NEEDS_REVIEW
                else ExtractionIssueSeverity.ERROR,
                field="event_datetime",
            )
            for code in codes
        ),
    )


def _result(
    fixture_name: str = "assessment",
    *,
    validation: ExtractionValidationResult | None = None,
    company_status: str = "resolved",
    candidate_ids: tuple[UUID, ...] = (),
) -> WorkflowExtractionResult:
    fixture = _fixture(fixture_name)
    extraction = RecruitmentExtraction.model_validate(fixture["response"])
    company = None
    role = None
    if extraction.relevant:
        company = CompanyResolutionEvidence(
            raw_company_name=extraction.company_raw,
            company_id=COMPANY_ID if company_status == "resolved" else None,
            status=company_status,
            method="alias_exact" if company_status == "resolved" else company_status,
            confidence=1.0 if company_status == "resolved" else 0.0,
            matched_value="nimbus labs" if company_status == "resolved" else None,
            candidate_company_ids=candidate_ids,
        )
        role = RoleResolutionEvidence(
            raw_name=extraction.role_raw,
            normalized_name=None
            if extraction.role_raw is None
            else extraction.role_raw.casefold(),
            family="software_engineering",
        )
    return WorkflowExtractionResult(
        extraction=extraction,
        validation=validation or _validation(ExtractionValidationStatus.VALID),
        prompt_version=RECRUITMENT_EXTRACTION_PROMPT_VERSION,
        company=company,
        role=role,
        company_resolution_audit_id=None,
    )


def _runner(
    activities: FakeActivities,
    persistence: FakeWorkflowPersistence,
    *,
    checkpointer: InMemorySaver | None = None,
    domain_store: FakeDomainStore | None = None,
    calendar: CalendarSync | None = None,
) -> RecruitmentWorkflowRunner:
    memory = checkpointer or InMemorySaver()
    graph = build_recruitment_graph(checkpointer=memory)
    return RecruitmentWorkflowRunner(
        graph=graph,
        context=RecruitmentGraphContext(
            activities=activities,
            domain=RecruitmentDomainService(domain_store or FakeDomainStore()),
            persistence=persistence,
            calendar=calendar or NoOpCalendarSync(),
            clock=FixedClock(),
        ),
    )


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        source_email_id=SOURCE_EMAIL_ID,
        model_deployment="structured-model",
        processing_run_id=RUN_ID,
    )


def _ambiguous_time_result(
    event_datetime: datetime | None,
    *codes: ExtractionIssueCode,
) -> WorkflowExtractionResult:
    """Timezone-ambiguous interview evidence with a configurable wall clock."""
    base = _result(
        "interview_without_timezone",
        validation=_validation(
            ExtractionValidationStatus.NEEDS_REVIEW,
            *(codes or (ExtractionIssueCode.TIMEZONE_AMBIGUOUS,)),
        ),
    )
    extraction = base.extraction.model_copy(update={"event_datetime": event_datetime})
    return base.model_copy(update={"extraction": extraction})


@pytest.mark.asyncio
async def test_happy_path_persists_phase_six_domain_plan() -> None:
    persistence = FakeWorkflowPersistence()
    activities = FakeActivities(prepared=_prepared(), extraction=_result())

    outcome = await _runner(activities, persistence).start(_request())

    assert outcome.state["status"] == ProcessingRunStatus.COMPLETED.value
    assert not outcome.interrupted
    assert outcome.state["application_id"] is not None
    assert outcome.state["event_id"] is not None
    assert len(outcome.state["action_item_ids"]) == 1
    assert outcome.state["calendar_operation"] == {
        "operation": "disabled",
        "reason": "calendar_sync_disabled",
    }
    assert persistence.final_status is ProcessingRunStatus.COMPLETED
    assert WorkflowStage.PERSIST_DOMAIN_CHANGES in persistence.stages
    assert activities.extract_calls == 1


@pytest.mark.asyncio
async def test_unsafe_calendar_update_interrupts_then_replaces_after_review() -> None:
    persistence = FakeWorkflowPersistence()
    activities = FakeActivities(prepared=_prepared(), extraction=_result())
    calendar = ReviewableCalendarSync()
    runner = _runner(activities, persistence, calendar=calendar)

    interrupted = await runner.start(_request())
    resumed = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice="apply_proposed_update"),
    )

    assert interrupted.interrupted
    payload = interrupted.interrupt_payloads[0]
    assert payload["review_type"] == "UNSAFE_CALENDAR_UPDATE"
    assert payload["reason"] == "linked_calendar_event_missing"
    assert payload["allowed_choices"] == [
        "apply_proposed_update",
        "skip_calendar_update",
        "ignore",
    ]
    assert resumed.state["status"] == ProcessingRunStatus.COMPLETED.value
    assert resumed.state["calendar_operation"] == {
        "operation": "created",
        "reason": "missing_calendar_event_replaced",
    }
    assert [request.replace_missing_event for request in calendar.requests] == [False, True]


@pytest.mark.asyncio
async def test_source_identity_is_loaded_atomically_before_mail_fetch() -> None:
    persistence = MismatchedSourcePersistence()
    activities = FakeActivities(prepared=_prepared(), extraction=_result())

    with pytest.raises(ValueError, match="identity does not match"):
        await _runner(activities, persistence).start(_request())

    assert activities.prepare_calls == 0
    assert not persistence.runs


@pytest.mark.asyncio
async def test_unlikely_prefilter_ends_without_model_invocation() -> None:
    persistence = FakeWorkflowPersistence()
    activities = FakeActivities(
        prepared=_prepared(prefilter=WorkflowPrefilterDecision.UNLIKELY),
        extraction=_result(),
    )

    outcome = await _runner(activities, persistence).start(_request())

    assert outcome.state["status"] == ProcessingRunStatus.IGNORED.value
    assert activities.extract_calls == 0
    assert persistence.final_status is ProcessingRunStatus.IGNORED


@pytest.mark.asyncio
async def test_model_classified_irrelevant_email_ends_ignored() -> None:
    persistence = FakeWorkflowPersistence()
    activities = FakeActivities(
        prepared=_prepared(prefilter=WorkflowPrefilterDecision.UNKNOWN),
        extraction=_result("non_recruitment"),
    )

    outcome = await _runner(activities, persistence).start(_request())

    assert outcome.state["status"] == ProcessingRunStatus.IGNORED.value
    assert activities.extract_calls == 1


@pytest.mark.asyncio
async def test_invalid_extraction_fails_before_placeholder_mutations() -> None:
    persistence = FakeWorkflowPersistence()
    invalid = _result(
        validation=_validation(
            ExtractionValidationStatus.INVALID,
            ExtractionIssueCode.UNKNOWN_LINK_REF,
        )
    )

    outcome = await _runner(
        FakeActivities(prepared=_prepared(), extraction=invalid),
        persistence,
    ).start(_request())

    assert outcome.state["status"] == ProcessingRunStatus.FAILED.value
    assert persistence.final_status is ProcessingRunStatus.FAILED
    assert persistence.error_code == "LLM_SCHEMA_INVALID"
    assert WorkflowStage.RESOLVE_APPLICATION not in persistence.stages


@pytest.mark.asyncio
async def test_timezone_interrupt_rejects_invalid_choice_then_resumes() -> None:
    persistence = FakeWorkflowPersistence()
    domain_store = FakeDomainStore()
    needs_timezone = _ambiguous_time_result(
        datetime(2026, 8, 20, 14, tzinfo=UTC),
        ExtractionIssueCode.TIMEZONE_AMBIGUOUS,
    )
    runner = _runner(
        FakeActivities(prepared=_prepared(), extraction=needs_timezone),
        persistence,
        domain_store=domain_store,
    )

    interrupted = await runner.start(_request())
    invalid = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice="not-allowed"),
    )
    resumed = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice="Europe/London"),
    )

    assert interrupted.interrupted
    assert interrupted.interrupt_payloads[0]["review_type"] == "TIMEZONE_AMBIGUITY"
    assert persistence.needs_review_marks[0] == SOURCE_EMAIL_ID
    assert invalid.interrupted
    assert invalid.interrupt_payloads[0]["validation_error"] == "invalid_review_decision"
    assert resumed.state["status"] == ProcessingRunStatus.COMPLETED.value
    assert len(persistence.reviews) == 1
    assert len(persistence.resolutions) == 1
    # The reviewed timezone must rebind the extracted wall clock, not merely
    # relabel it: 14:00 with an invented UTC offset becomes 14:00 London time.
    assert domain_store.plans[0].event.starts_at == datetime(
        2026, 8, 20, 14, tzinfo=ZoneInfo("Europe/London")
    )
    assert domain_store.plans[0].event.timezone == "Europe/London"


@pytest.mark.asyncio
async def test_extracted_wall_clock_completes_after_timezone_confirmation() -> None:
    """A named local time without a zone needs timezone supervision only."""
    persistence = FakeWorkflowPersistence()
    domain_store = FakeDomainStore()
    needs_timezone = _result(
        "interview_without_timezone",
        validation=_validation(
            ExtractionValidationStatus.NEEDS_REVIEW,
            ExtractionIssueCode.TIMEZONE_AMBIGUOUS,
        ),
    )
    runner = _runner(
        FakeActivities(prepared=_prepared(), extraction=needs_timezone),
        persistence,
        domain_store=domain_store,
    )

    interrupted = await runner.start(_request())
    completed = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice="Asia/Shanghai"),
    )

    assert interrupted.interrupt_payloads[0]["review_type"] == "TIMEZONE_AMBIGUITY"
    assert completed.state["status"] == ProcessingRunStatus.COMPLETED.value
    assert not completed.interrupted
    assert domain_store.plans[0].event.starts_at == datetime(
        2026, 8, 20, 14, tzinfo=ZoneInfo("Asia/Shanghai")
    )


@pytest.mark.asyncio
async def test_unresolved_datetime_and_timezone_are_asked_together() -> None:
    """Missing clock plus missing timezone stay on one review page."""
    persistence = FakeWorkflowPersistence()
    domain_store = FakeDomainStore()
    needs_both = _ambiguous_time_result(
        None,
        ExtractionIssueCode.DATETIME_UNRESOLVED,
        ExtractionIssueCode.TIMEZONE_AMBIGUOUS,
    )
    runner = _runner(
        FakeActivities(prepared=_prepared(), extraction=needs_both),
        persistence,
        domain_store=domain_store,
    )

    interrupted = await runner.start(_request())
    completed = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(
            choice="Asia/Shanghai",
            clock_override="2026-08-20 15:00",
        ),
    )

    assert interrupted.interrupt_payloads[0]["review_type"] == "TIMEZONE_AMBIGUITY"
    assert interrupted.interrupt_payloads[0]["reason"] == "timezone_and_datetime"
    assert completed.state["status"] == ProcessingRunStatus.COMPLETED.value
    assert not completed.interrupted
    assert domain_store.plans[0].event.starts_at == datetime(
        2026, 8, 20, 15, tzinfo=ZoneInfo("Asia/Shanghai")
    )


@pytest.mark.asyncio
async def test_finished_run_is_never_reexecuted_by_a_stale_retry() -> None:
    """Regression: a lease-expired retry with the same run id must not drag a
    PROCESSED email back through the graph."""
    persistence = FakeWorkflowPersistence()
    persistence.stored_run_status = ProcessingRunStatus.COMPLETED
    activities = FakeActivities(prepared=_prepared(), extraction=_result())

    outcome = await _runner(activities, persistence).start(_request())

    assert outcome.state["status"] == ProcessingRunStatus.COMPLETED.value
    assert not outcome.interrupted
    assert activities.prepare_calls == 0
    assert persistence.stages == []


@pytest.mark.asyncio
async def test_company_identity_ambiguity_can_select_reviewed_candidate() -> None:
    persistence = FakeWorkflowPersistence()
    ambiguous = _result(
        company_status="ambiguous",
        candidate_ids=(COMPANY_ID, OTHER_COMPANY_ID),
    )
    runner = _runner(
        FakeActivities(prepared=_prepared(), extraction=ambiguous),
        persistence,
    )

    interrupted = await runner.start(_request())
    resumed = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice=str(COMPANY_ID)),
    )

    assert interrupted.interrupt_payloads[0]["review_type"] == "APPLICATION_AMBIGUITY"
    assert str(COMPANY_ID) in interrupted.interrupt_payloads[0]["allowed_choices"]
    assert resumed.state["application_id"] != str(COMPANY_ID)
    assert resumed.state["application_id"] is not None
    assert resumed.state["status"] == ProcessingRunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_application_ambiguity_resumes_with_selected_application() -> None:
    persistence = FakeWorkflowPersistence()
    candidates = (
        ApplicationSnapshot(
            id=APPLICATION_ID,
            company_id=COMPANY_ID,
            role_normalized="graduate engineer",
            status=ApplicationStatus.APPLIED,
            version=1,
        ),
        ApplicationSnapshot(
            id=OTHER_APPLICATION_ID,
            company_id=COMPANY_ID,
            role_normalized="graduate engineer",
            status=ApplicationStatus.APPLIED,
            version=1,
        ),
    )
    runner = _runner(
        FakeActivities(prepared=_prepared(), extraction=_result()),
        persistence,
        domain_store=FakeDomainStore(applications=candidates),
    )

    interrupted = await runner.start(_request())
    resumed = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice=str(APPLICATION_ID)),
    )

    assert interrupted.interrupt_payloads[0]["review_type"] == "APPLICATION_AMBIGUITY"
    assert str(APPLICATION_ID) in interrupted.interrupt_payloads[0]["allowed_choices"]
    assert resumed.state["application_id"] == str(APPLICATION_ID)
    assert resumed.state["status"] == ProcessingRunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_uncertain_reschedule_resumes_with_selected_existing_event() -> None:
    persistence = FakeWorkflowPersistence()
    application = ApplicationSnapshot(
        id=APPLICATION_ID,
        company_id=COMPANY_ID,
        role_normalized="backend developer",
        status=ApplicationStatus.INTERVIEW_SCHEDULED,
        version=2,
    )
    events = tuple(
        EventSnapshot(
            id=event_id,
            application_id=APPLICATION_ID,
            type=RecruitmentEventType.INTERVIEW,
            status=EventStatus.ACTIVE,
            round="second interview",
            starts_at=datetime(2026, 8, 20, 13, tzinfo=UTC),
            deadline_at=None,
            timezone="BST",
            source_datetime_text="20 August 2026 at 14:00 BST",
            semantic_fingerprint=f"fingerprint-{index}",
        )
        for index, event_id in enumerate((EVENT_ID, OTHER_EVENT_ID), start=1)
    )
    runner = _runner(
        FakeActivities(prepared=_prepared(), extraction=_result("reschedule")),
        persistence,
        domain_store=FakeDomainStore(linked=application, events=events),
    )

    interrupted = await runner.start(_request())
    resumed = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice=str(EVENT_ID)),
    )

    assert interrupted.interrupt_payloads[0]["review_type"] == "UNCERTAIN_RESCHEDULE"
    assert resumed.state["event_id"] == str(EVENT_ID)
    assert resumed.state["status"] == ProcessingRunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_conflicting_datetime_interrupt_resumes_through_typed_choice() -> None:
    persistence = FakeWorkflowPersistence()
    conflict = _result(
        "interview",
        validation=_validation(
            ExtractionValidationStatus.NEEDS_REVIEW,
            ExtractionIssueCode.TIMEZONE_CONFLICT,
        ),
    )
    runner = _runner(
        FakeActivities(prepared=_prepared(), extraction=conflict),
        persistence,
    )

    interrupted = await runner.start(_request())
    resumed = await runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice="use_extracted"),
    )

    assert interrupted.interrupt_payloads[0]["review_type"] == "DATETIME_CONFLICT"
    assert resumed.state["status"] == ProcessingRunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_interrupt_survives_graph_reconstruction_with_same_checkpointer() -> None:
    memory = InMemorySaver()
    persistence = FakeWorkflowPersistence()
    result = _ambiguous_time_result(datetime(2026, 8, 20, 14, tzinfo=UTC))
    activities = FakeActivities(prepared=_prepared(), extraction=result)

    first_runner = _runner(activities, persistence, checkpointer=memory)
    assert (await first_runner.start(_request())).interrupted
    reconstructed_runner = _runner(activities, persistence, checkpointer=memory)
    resumed = await reconstructed_runner.resume(
        processing_run_id=RUN_ID,
        source_email_id=SOURCE_EMAIL_ID,
        decision=ReviewDecision(choice="Asia/Shanghai"),
    )

    assert resumed.state["status"] == ProcessingRunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_failure_audit_records_only_safe_error_class() -> None:
    persistence = FakeWorkflowPersistence()
    activities = FakeActivities(
        prepared=_prepared(),
        extraction=_result(),
        failure=RuntimeError("private@example.test token=plaintext-secret"),
    )

    with pytest.raises(RuntimeError, match="plaintext-secret"):
        await _runner(activities, persistence).start(_request())

    assert persistence.final_status is ProcessingRunStatus.FAILED
    assert persistence.error_code == "WORKFLOW_FAILED"
    assert persistence.error_detail == "RuntimeError"
    assert "plaintext-secret" not in repr(persistence.__dict__)


def test_review_item_identity_is_stable_and_contains_no_checkpoint_payload() -> None:
    request = _result(
        "interview_without_timezone",
        validation=_validation(
            ExtractionValidationStatus.NEEDS_REVIEW,
            ExtractionIssueCode.TIMEZONE_AMBIGUOUS,
        ),
    )
    assert request.validation.status is ExtractionValidationStatus.NEEDS_REVIEW

    review_request = ReviewItem.create(
        processing_run_id=RUN_ID,
        request=ReviewRequest(
            review_type=ReviewType.TIMEZONE_AMBIGUITY,
            reason="timezone_ambiguity",
            question="Select timezone.",
            allowed_choices=("Europe/London", "ignore"),
        ),
        created_at=NOW,
    )
    repeated = ReviewItem.create(
        processing_run_id=RUN_ID,
        request=review_request.request,
        created_at=NOW,
    )

    assert review_request.id == repeated.id
    assert review_request.status is ReviewStatus.OPEN
    assert "checkpoint" not in review_request.request.model_dump()


@pytest.mark.asyncio
async def test_open_review_after_resolve_creates_a_successor_row() -> None:
    persistence = FakeWorkflowPersistence()
    item = ReviewItem.create(
        processing_run_id=RUN_ID,
        request=ReviewRequest(
            review_type=ReviewType.TIMEZONE_AMBIGUITY,
            reason="timezone_ambiguity",
            question="Select timezone.",
            allowed_choices=("Europe/London", "ignore"),
        ),
        created_at=NOW,
    )

    first = await persistence.open_review(item)
    await persistence.resolve_review(
        review_id=first.id,
        decision=ReviewDecision(choice="Europe/London", expected_version=1),
        resolved_at=NOW,
    )
    second = await persistence.open_review(item)

    assert second.id != first.id
    assert second.id == successor_review_id(first.id, 2)
    assert persistence.reviews[first.id].status is ReviewStatus.RESOLVED
    assert second.status is ReviewStatus.OPEN
