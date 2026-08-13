from datetime import UTC, datetime
from uuid import UUID

import pytest

from recruitment_agent.application.calendar_sync import CalendarPlanner, CalendarSyncService
from recruitment_agent.application.errors import CalendarEventNotFoundError
from recruitment_agent.calendar.models import (
    CalendarCandidate,
    CalendarEventDraft,
    CalendarLinkSnapshot,
    CalendarProviderEvent,
    CalendarSyncOperation,
    CalendarSyncRequest,
)
from recruitment_agent.domain.enums import EventStatus, RecruitmentEventType
from recruitment_agent.domain.ports import Clock

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000701")
SOURCE_ID = UUID("00000000-0000-0000-0000-000000000702")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000703")
APPLICATION_ID = UUID("00000000-0000-0000-0000-000000000704")
NOW = datetime(2026, 8, 13, 20, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


def candidate(
    *,
    event_type: RecruitmentEventType = RecruitmentEventType.INTERVIEW,
    resolved: bool = True,
) -> CalendarCandidate:
    return CalendarCandidate(
        account_id=ACCOUNT_ID,
        source_email_id=SOURCE_ID,
        recruitment_event_id=EVENT_ID,
        application_id=APPLICATION_ID,
        application_resolved=resolved,
        company_display_name="Nimbus Labs" if resolved else None,
        role_name="Backend Engineer",
        event_type=event_type,
        event_status=EventStatus.ACTIVE,
        interview_round="1",
        starts_at=datetime(2026, 8, 20, 13, tzinfo=UTC),
        deadline_at=datetime(2026, 8, 21, 17, tzinfo=UTC),
        timezone="Europe/London",
        source_datetime_text="20 August 2026 at 14:00 BST",
        outlook_web_link="https://outlook.office.com/mail/id/opaque?secret=removed",
    )


class Store:
    def __init__(
        self,
        value: CalendarCandidate,
        link: CalendarLinkSnapshot | None = None,
    ) -> None:
        self.value = value
        self.link = link
        self.load_calls = 0

    async def load_candidate(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        recruitment_event_id: UUID,
    ) -> CalendarCandidate:
        assert (account_id, source_email_id, recruitment_event_id) == (
            ACCOUNT_ID,
            SOURCE_ID,
            EVENT_ID,
        )
        self.load_calls += 1
        return self.value

    async def get_link(self, recruitment_event_id: UUID) -> CalendarLinkSnapshot | None:
        assert recruitment_event_id == EVENT_ID
        return self.link

    async def save_link(self, link: CalendarLinkSnapshot) -> None:
        self.link = link


class Gateway:
    def __init__(self, *, missing_on_update: bool = False) -> None:
        self.missing_on_update = missing_on_update
        self.created: list[CalendarEventDraft] = []
        self.updated: list[CalendarEventDraft] = []

    async def create_event(
        self,
        *,
        account_id: UUID,
        draft: CalendarEventDraft,
    ) -> CalendarProviderEvent:
        assert account_id == ACCOUNT_ID
        self.created.append(draft)
        return CalendarProviderEvent(event_id="immutable-event-1")

    async def update_event(
        self,
        *,
        account_id: UUID,
        event_id: str,
        draft: CalendarEventDraft,
    ) -> CalendarProviderEvent:
        assert account_id == ACCOUNT_ID
        assert event_id == "immutable-event-1"
        if self.missing_on_update:
            raise CalendarEventNotFoundError("missing")
        self.updated.append(draft)
        return CalendarProviderEvent(event_id=event_id)


def request(**kwargs: bool) -> CalendarSyncRequest:
    return CalendarSyncRequest(
        account_id=ACCOUNT_ID,
        source_email_id=SOURCE_ID,
        recruitment_event_id=EVENT_ID,
        **kwargs,
    )


def service(store: Store, gateway: Gateway, *, enabled: bool = True) -> CalendarSyncService:
    return CalendarSyncService(
        store=store,
        gateway=gateway,
        planner=CalendarPlanner(),
        clock=FixedClock(),
        enabled=enabled,
    )


@pytest.mark.asyncio
async def test_create_is_idempotent_and_description_marks_placeholder() -> None:
    store = Store(candidate())
    gateway = Gateway()
    calendar = service(store, gateway)

    first = await calendar.sync(request())
    second = await calendar.sync(request())

    assert first.operation is CalendarSyncOperation.CREATED
    assert second.operation is CalendarSyncOperation.UNCHANGED
    assert len(gateway.created) == 1
    draft = gateway.created[0]
    assert draft.subject == "Nimbus Labs | Backend Engineer | Interview 1"
    assert "60-minute placeholder" in draft.body
    assert "?secret=" not in draft.body
    assert draft.transaction_id


@pytest.mark.asyncio
async def test_changed_domain_state_updates_the_existing_calendar_event() -> None:
    original = CalendarPlanner().plan(candidate(), has_existing_link=False).draft
    assert original is not None
    link = CalendarLinkSnapshot(
        recruitment_event_id=EVENT_ID,
        account_id=ACCOUNT_ID,
        provider="microsoft_graph",
        calendar_event_id="immutable-event-1",
        content_fingerprint="0" * 64,
        last_synced_at=NOW,
    )
    store = Store(candidate(event_type=RecruitmentEventType.ASSESSMENT), link)
    gateway = Gateway()

    result = await service(store, gateway).sync(request())

    assert result.operation is CalendarSyncOperation.UPDATED
    assert len(gateway.updated) == 1
    assert "Assessment Deadline" in gateway.updated[0].subject


@pytest.mark.asyncio
async def test_missing_linked_provider_event_requires_review_before_replacement() -> None:
    link = CalendarLinkSnapshot(
        recruitment_event_id=EVENT_ID,
        account_id=ACCOUNT_ID,
        provider="microsoft_graph",
        calendar_event_id="immutable-event-1",
        content_fingerprint="0" * 64,
        last_synced_at=NOW,
    )
    store = Store(candidate(), link)
    gateway = Gateway(missing_on_update=True)

    result = await service(store, gateway).sync(request())
    replaced = await service(store, gateway).sync(request(replace_missing_event=True))

    assert result.operation is CalendarSyncOperation.REVIEW_REQUIRED
    assert result.reason == "linked_calendar_event_missing"
    assert replaced.operation is CalendarSyncOperation.CREATED


@pytest.mark.asyncio
async def test_disabled_boundary_does_not_load_database_or_call_graph() -> None:
    store = Store(candidate())
    gateway = Gateway()

    result = await service(store, gateway, enabled=False).sync(request())

    assert result.operation is CalendarSyncOperation.DISABLED
    assert store.load_calls == 0
    assert not gateway.created


@pytest.mark.asyncio
async def test_unresolved_application_never_mutates_calendar() -> None:
    store = Store(candidate(resolved=False))
    gateway = Gateway()

    result = await service(store, gateway).sync(request())

    assert result.operation is CalendarSyncOperation.REVIEW_REQUIRED
    assert not gateway.created
