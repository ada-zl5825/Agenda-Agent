"""Pure Phase 6 resolver, duplicate, reschedule, and transition tests."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from recruitment_agent.application.domain_processing import RecruitmentDomainService
from recruitment_agent.domain.enums import ApplicationStatus, EventStatus, RecruitmentEventType
from recruitment_agent.domain.processing import (
    ApplicationResolutionKind,
    ApplicationSnapshot,
    DomainMutationResult,
    DomainTransitionPlan,
    EventMutationKind,
    EventResolutionKind,
    EventSnapshot,
    RecruitmentEvidence,
    next_application_status,
    semantic_fingerprint,
)

SOURCE_ID = UUID("10000000-0000-0000-0000-000000000001")
COMPANY_ID = UUID("10000000-0000-0000-0000-000000000002")
APPLICATION_ID = UUID("10000000-0000-0000-0000-000000000003")
OTHER_APPLICATION_ID = UUID("10000000-0000-0000-0000-000000000004")
EVENT_ID = UUID("10000000-0000-0000-0000-000000000005")
OTHER_EVENT_ID = UUID("10000000-0000-0000-0000-000000000006")
STARTS_AT = datetime(2026, 8, 20, 13, tzinfo=UTC)
DEADLINE = datetime(2026, 8, 18, 16, tzinfo=UTC)


class StubStore:
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

    async def application_for_source_email(
        self,
        source_email_id: UUID,
    ) -> ApplicationSnapshot | None:
        assert source_email_id == SOURCE_ID
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
        return tuple(
            item
            for item in self.events
            if item.application_id == application_id
            and item.type is RecruitmentEventType.INTERVIEW
            and item.status is EventStatus.ACTIVE
        )

    async def apply_transition(
        self,
        plan: DomainTransitionPlan,
    ) -> DomainMutationResult:
        raise AssertionError(f"unit resolver test must not persist {plan!r}")


def _application(
    application_id: UUID = APPLICATION_ID,
    *,
    status: ApplicationStatus = ApplicationStatus.APPLIED,
) -> ApplicationSnapshot:
    return ApplicationSnapshot(
        id=application_id,
        company_id=COMPANY_ID,
        role_normalized="software engineer",
        status=status,
        version=1,
    )


def _evidence(
    event_type: RecruitmentEventType,
    *,
    starts_at: datetime | None = STARTS_AT,
    deadline: datetime | None = None,
    action_required: bool = False,
    unresolved_datetime: bool = False,
) -> RecruitmentEvidence:
    return RecruitmentEvidence(
        source_email_id=SOURCE_ID,
        company_id=COMPANY_ID,
        raw_company_name="Nimbus Labs",
        role_name="Software Engineer",
        role_normalized="software engineer",
        event_type=event_type,
        interview_round="first round"
        if event_type
        in {RecruitmentEventType.INTERVIEW, RecruitmentEventType.INTERVIEW_RESCHEDULE}
        else None,
        action_required=action_required,
        action_text="Complete the requested step" if action_required else None,
        action_link_ref="ACTION_LINK_01" if action_required else None,
        event_datetime=starts_at,
        deadline=deadline,
        timezone="BST" if starts_at is not None or deadline is not None else None,
        source_datetime_text=(
            "next Tuesday at 10:00"
            if unresolved_datetime
            else "20 August 2026 at 14:00 BST"
            if starts_at is not None
            else None
        ),
    )


def _event(
    event_id: UUID = EVENT_ID,
    *,
    fingerprint: str | None = None,
    round_name: str | None = "first round",
) -> EventSnapshot:
    return EventSnapshot(
        id=event_id,
        application_id=APPLICATION_ID,
        type=RecruitmentEventType.INTERVIEW,
        status=EventStatus.ACTIVE,
        round=round_name,
        starts_at=datetime(2026, 8, 19, 13, tzinfo=UTC),
        deadline_at=None,
        timezone="BST",
        source_datetime_text="19 August 2026 at 14:00 BST",
        semantic_fingerprint=fingerprint,
    )


@pytest.mark.asyncio
async def test_assessment_creates_application_event_action_and_pending_status() -> None:
    evidence = _evidence(
        RecruitmentEventType.ASSESSMENT,
        starts_at=None,
        deadline=DEADLINE,
        action_required=True,
    )
    service = RecruitmentDomainService(StubStore())

    application = await service.resolve_application(evidence)
    event = await service.resolve_event(evidence, application)
    plan = service.plan_transition(evidence, application, event)

    assert application.kind is ApplicationResolutionKind.CREATE
    assert event.kind is EventResolutionKind.CREATE
    assert plan.application_status_after is ApplicationStatus.ASSESSMENT_PENDING
    assert plan.event.kind is EventMutationKind.CREATE
    assert plan.action_item is not None
    assert plan.action_item.secure_link_ref == "ACTION_LINK_01"
    assert len(plan.action_item.idempotency_key) == 64


@pytest.mark.asyncio
async def test_multiple_exact_open_applications_require_review() -> None:
    evidence = _evidence(RecruitmentEventType.INTERVIEW)
    service = RecruitmentDomainService(
        StubStore(applications=(_application(), _application(OTHER_APPLICATION_ID)))
    )

    resolution = await service.resolve_application(evidence)

    assert resolution.kind is ApplicationResolutionKind.REVIEW
    assert set(resolution.candidate_application_ids) == {
        APPLICATION_ID,
        OTHER_APPLICATION_ID,
    }


@pytest.mark.asyncio
async def test_reviewed_create_new_is_preserved_in_transition_plan() -> None:
    evidence = _evidence(RecruitmentEventType.INTERVIEW)
    service = RecruitmentDomainService(
        StubStore(applications=(_application(), _application(OTHER_APPLICATION_ID)))
    )

    application = await service.resolve_application(evidence, force_create=True)
    event = await service.resolve_event(evidence, application)
    plan = service.plan_transition(evidence, application, event)

    assert application.kind is ApplicationResolutionKind.CREATE
    assert plan.create_application
    assert plan.reviewed_create_new_application


@pytest.mark.asyncio
async def test_semantic_duplicate_reuses_existing_event_identity() -> None:
    evidence = _evidence(RecruitmentEventType.INTERVIEW)
    existing = _event(fingerprint=semantic_fingerprint(evidence))
    service = RecruitmentDomainService(
        StubStore(linked=_application(), events=(existing,))
    )

    application = await service.resolve_application(evidence)
    event = await service.resolve_event(evidence, application)
    plan = service.plan_transition(evidence, application, event)

    assert event.kind is EventResolutionKind.DUPLICATE
    assert event.event_id == EVENT_ID
    assert plan.event.kind is EventMutationKind.NONE


@pytest.mark.asyncio
async def test_reschedule_updates_the_single_matching_interview() -> None:
    evidence = _evidence(RecruitmentEventType.INTERVIEW_RESCHEDULE)
    service = RecruitmentDomainService(
        StubStore(linked=_application(), events=(_event(),))
    )

    application = await service.resolve_application(evidence)
    event = await service.resolve_event(evidence, application)
    plan = service.plan_transition(evidence, application, event)

    assert event.kind is EventResolutionKind.RESCHEDULE
    assert event.event_id == EVENT_ID
    assert plan.event.kind is EventMutationKind.UPDATE
    assert plan.event.event_id == EVENT_ID


@pytest.mark.asyncio
async def test_ambiguous_reschedule_lists_candidates_without_guessing() -> None:
    evidence = _evidence(RecruitmentEventType.INTERVIEW_RESCHEDULE)
    service = RecruitmentDomainService(
        StubStore(
            linked=_application(),
            events=(_event(), _event(OTHER_EVENT_ID)),
        )
    )

    application = await service.resolve_application(evidence)
    event = await service.resolve_event(evidence, application)

    assert event.kind is EventResolutionKind.REVIEW
    assert set(event.candidate_event_ids) == {EVENT_ID, OTHER_EVENT_ID}


@pytest.mark.asyncio
async def test_unresolved_interview_datetime_produces_zero_mutation_plan() -> None:
    evidence = _evidence(
        RecruitmentEventType.INTERVIEW,
        starts_at=None,
        unresolved_datetime=True,
    )
    service = RecruitmentDomainService(StubStore())

    application = await service.resolve_application(evidence)
    event = await service.resolve_event(evidence, application)
    plan = service.plan_transition(evidence, application, event)

    assert not plan.mutations_allowed
    assert plan.no_mutation_reason == "event_datetime_unresolved"
    assert plan.application_status_after is ApplicationStatus.UNKNOWN
    assert plan.event.kind is EventMutationKind.NONE
    assert plan.action_item is None


@pytest.mark.asyncio
async def test_undated_interview_without_time_evidence_becomes_pending() -> None:
    evidence = _evidence(RecruitmentEventType.INTERVIEW, starts_at=None)
    service = RecruitmentDomainService(StubStore())

    application = await service.resolve_application(evidence)
    event = await service.resolve_event(evidence, application)
    plan = service.plan_transition(evidence, application, event)

    assert plan.mutations_allowed
    assert plan.application_status_after is ApplicationStatus.INTERVIEW_PENDING
    assert plan.event.kind is EventMutationKind.CREATE


def test_terminal_status_is_not_downgraded_by_older_evidence() -> None:
    assert (
        next_application_status(
            ApplicationStatus.OFFER,
            ApplicationStatus.INTERVIEW_SCHEDULED,
        )
        is ApplicationStatus.OFFER
    )
    assert (
        next_application_status(
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.OFFER,
        )
        is ApplicationStatus.WITHDRAWN
    )


def test_semantic_fingerprint_normalizes_equivalent_datetime_offsets() -> None:
    london = _evidence(RecruitmentEventType.INTERVIEW)
    china_offset = timezone(timedelta(hours=8))
    equivalent = london.model_copy(
        update={"event_datetime": STARTS_AT.astimezone(china_offset)}
    )

    assert semantic_fingerprint(london) == semantic_fingerprint(equivalent)


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (RecruitmentEventType.APPLICATION_RECEIVED, ApplicationStatus.APPLIED),
        (RecruitmentEventType.ASSESSMENT, ApplicationStatus.ASSESSMENT_PENDING),
        (RecruitmentEventType.INTERVIEW, ApplicationStatus.INTERVIEW_SCHEDULED),
        (RecruitmentEventType.OFFER, ApplicationStatus.OFFER),
        (RecruitmentEventType.REJECTION, ApplicationStatus.REJECTED),
    ],
)
@pytest.mark.asyncio
async def test_key_event_types_map_to_deterministic_application_statuses(
    event_type: RecruitmentEventType,
    expected: ApplicationStatus,
) -> None:
    starts_at = STARTS_AT if event_type is RecruitmentEventType.INTERVIEW else None
    evidence = _evidence(event_type, starts_at=starts_at)
    service = RecruitmentDomainService(StubStore())

    application = await service.resolve_application(evidence)
    event = await service.resolve_event(evidence, application)
    plan = service.plan_transition(evidence, application, event)

    assert plan.application_status_after is expected
