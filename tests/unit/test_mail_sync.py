from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from recruitment_agent.application.errors import DeltaStateInvalidError
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
    def __init__(self, pages: dict[str | None, MailDeltaPage]) -> None:
        self.pages = pages
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
        return self.pages[cursor]


class Store:
    def __init__(self) -> None:
        self.delta_link: str | None = None
        self.messages: dict[str, SourceEmailCandidate] = {}
        self.error_code: str | None = None

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
        inserted = 0
        updated = 0
        for message in messages:
            if message.graph_message_id in self.messages:
                updated += 1
            else:
                inserted += 1
            self.messages[message.graph_message_id] = message
        self.delta_link = delta_link
        return MailIngestionResult(inserted=inserted, updated=updated)

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
async def test_records_privacy_safe_failure_code_for_invalid_delta_response() -> None:
    gateway = Gateway(
        {None: MailDeltaPage(messages=(), next_link=None, delta_link=None)}
    )
    store = Store()
    service = MailSyncService(gateway=gateway, store=store, clock=Clock())

    with pytest.raises(DeltaStateInvalidError):
        await service.synchronize(account_id=uuid4(), folder_id="inbox")

    assert store.error_code == "DELTA_STATE_INVALID"
