from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from recruitment_agent.application.errors import (
    DeltaStateInvalidError,
    GraphFetchError,
    MailSyncPageLimitError,
)
from recruitment_agent.application.mail_sync import (
    MailDeltaPage,
    MailIngestionResult,
    MailSyncService,
)
from recruitment_agent.domain.mail import (
    MailSyncState,
    MailSyncStatus,
    SourceEmailCandidate,
)

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Gateway:
    def __init__(
        self,
        pages: dict[str | None, MailDeltaPage],
        *,
        failures: dict[str | None, Exception] | None = None,
    ) -> None:
        self.pages = pages
        self.failures = failures or {}
        self.cursors: list[str | None] = []

    async def fetch_delta_page(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        cursor: str | None,
    ) -> MailDeltaPage:
        del account_id, folder_id
        self.cursors.append(cursor)
        failure = self.failures.get(cursor)
        if failure is not None:
            raise failure
        return self.pages[cursor]


class Store:
    def __init__(self) -> None:
        self.delta_link: str | None = None
        self.messages: dict[str, SourceEmailCandidate] = {}
        self.error_code: str | None = None
        self.cursor_invalidated = False

    def _ingest(
        self,
        messages: tuple[SourceEmailCandidate, ...],
    ) -> MailIngestionResult:
        inserted = 0
        updated = 0
        for message in messages:
            if message.graph_message_id in self.messages:
                updated += 1
            else:
                inserted += 1
            self.messages[message.graph_message_id] = message
        return MailIngestionResult(inserted=inserted, updated=updated)

    async def begin_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        started_at: datetime,
    ) -> MailSyncState:
        return MailSyncState(
            account_id=account_id,
            folder_id=folder_id,
            delta_link=self.delta_link,
            last_sync_started_at=started_at,
            last_sync_finished_at=None,
            status=MailSyncStatus.SYNCING,
        )

    async def ingest_page(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        messages: tuple[SourceEmailCandidate, ...],
        cursor: str,
    ) -> MailIngestionResult:
        del account_id, folder_id
        result = self._ingest(messages)
        self.delta_link = cursor
        return result

    async def complete_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        messages: tuple[SourceEmailCandidate, ...],
        delta_link: str,
        finished_at: datetime,
    ) -> MailIngestionResult:
        del account_id, folder_id, finished_at
        result = self._ingest(messages)
        self.delta_link = delta_link
        return result

    async def fail_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        error_code: str,
        finished_at: datetime,
    ) -> None:
        del account_id, folder_id, finished_at
        self.error_code = error_code

    async def invalidate_cursor(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        error_code: str,
        finished_at: datetime,
    ) -> None:
        del account_id, folder_id, finished_at
        self.error_code = error_code
        self.delta_link = None
        self.cursor_invalidated = True


def candidate(message_id: str) -> SourceEmailCandidate:
    return SourceEmailCandidate(
        graph_message_id=message_id,
        internet_message_id=None,
        subject="Assessment",
        sender_domain="example.com",
        received_at=NOW,
        outlook_web_link=None,
        has_attachments=False,
    )


@pytest.mark.asyncio
async def test_follows_pages_and_reuses_terminal_delta_link_idempotently() -> None:
    next_link = "https://graph.microsoft.com/v1.0/next"
    final_link = "https://graph.microsoft.com/v1.0/delta"
    gateway = Gateway(
        {
            None: MailDeltaPage(messages=(candidate("1"),), next_link=next_link, delta_link=None),
            next_link: MailDeltaPage(
                messages=(candidate("2"),),
                next_link=None,
                delta_link=final_link,
            ),
            final_link: MailDeltaPage(
                messages=(candidate("2"),),
                next_link=None,
                delta_link=final_link,
            ),
        }
    )
    store = Store()
    service = MailSyncService(gateway=gateway, store=store, clock=Clock())
    account_id = uuid4()

    first = await service.synchronize(account_id=account_id, folder_id="inbox")
    second = await service.synchronize(account_id=account_id, folder_id="inbox")

    assert (first.inserted, first.updated) == (2, 0)
    assert (second.inserted, second.updated) == (0, 1)
    assert gateway.cursors == [None, next_link, final_link]
    assert set(store.messages) == {"1", "2"}


@pytest.mark.asyncio
async def test_invalid_delta_response_clears_the_cursor_for_a_full_resync() -> None:
    gateway = Gateway(
        {None: MailDeltaPage(messages=(), next_link=None, delta_link=None)}
    )
    store = Store()
    store.delta_link = None
    service = MailSyncService(gateway=gateway, store=store, clock=Clock())

    with pytest.raises(DeltaStateInvalidError):
        await service.synchronize(account_id=uuid4(), folder_id="inbox")

    assert store.error_code == "DELTA_STATE_INVALID"
    assert store.cursor_invalidated


@pytest.mark.asyncio
async def test_expired_delta_cursor_recovers_instead_of_wedging_every_sync() -> None:
    """Regression: Graph 410 must clear the stored cursor so the next run
    performs a fresh full enumeration rather than failing forever."""
    stale = "https://graph.microsoft.com/v1.0/stale-delta"
    gateway = Gateway(
        {},
        failures={stale: DeltaStateInvalidError("Graph delta cursor is no longer valid")},
    )
    store = Store()
    store.delta_link = stale
    service = MailSyncService(gateway=gateway, store=store, clock=Clock())

    with pytest.raises(DeltaStateInvalidError):
        await service.synchronize(account_id=uuid4(), folder_id="inbox")

    assert store.cursor_invalidated
    assert store.delta_link is None


@pytest.mark.asyncio
async def test_each_page_commits_progress_before_the_next_fetch() -> None:
    """Regression: a failure on page two must not lose page one or its cursor."""
    next_link = "https://graph.microsoft.com/v1.0/next"
    gateway = Gateway(
        {
            None: MailDeltaPage(
                messages=(candidate("1"),),
                next_link=next_link,
                delta_link=None,
            ),
        },
        failures={next_link: GraphFetchError("transient outage")},
    )
    store = Store()
    service = MailSyncService(gateway=gateway, store=store, clock=Clock())

    with pytest.raises(GraphFetchError):
        await service.synchronize(account_id=uuid4(), folder_id="inbox")

    assert set(store.messages) == {"1"}
    assert store.delta_link == next_link
    assert store.error_code == "GRAPH_FETCH_FAILED"
    assert not store.cursor_invalidated


@pytest.mark.asyncio
async def test_page_budget_exhaustion_keeps_progress_and_is_retryable() -> None:
    """Regression: a huge initial sync must resume next run, not fail forever."""
    first = "https://graph.microsoft.com/v1.0/page-1"
    second = "https://graph.microsoft.com/v1.0/page-2"
    gateway = Gateway(
        {
            None: MailDeltaPage(messages=(candidate("1"),), next_link=first, delta_link=None),
            first: MailDeltaPage(messages=(candidate("2"),), next_link=second, delta_link=None),
        }
    )
    store = Store()
    service = MailSyncService(gateway=gateway, store=store, clock=Clock(), max_pages=2)

    with pytest.raises(MailSyncPageLimitError):
        await service.synchronize(account_id=uuid4(), folder_id="inbox")

    assert set(store.messages) == {"1", "2"}
    assert store.delta_link == second
    assert store.error_code == "SYNC_PAGE_LIMIT"
    assert not store.cursor_invalidated


@pytest.mark.asyncio
async def test_unexpected_failure_marks_the_sync_failed_instead_of_stuck() -> None:
    gateway = Gateway({}, failures={None: RuntimeError("boom")})
    store = Store()
    service = MailSyncService(gateway=gateway, store=store, clock=Clock())

    with pytest.raises(RuntimeError):
        await service.synchronize(account_id=uuid4(), folder_id="inbox")

    assert store.error_code == "SYNC_UNEXPECTED"
