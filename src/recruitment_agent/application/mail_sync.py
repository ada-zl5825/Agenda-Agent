"""Deterministic, idempotent mail delta synchronization."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from recruitment_agent.application.errors import ApplicationError, DeltaStateInvalidError
from recruitment_agent.domain.mail import MailSyncState, SourceEmailCandidate
from recruitment_agent.domain.ports import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class MailDeltaPage:
    """Provider-neutral page returned by a mail change-tracking gateway."""

    messages: tuple[SourceEmailCandidate, ...]
    next_link: str | None
    delta_link: str | None


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class FetchedMail:
    """Transient full message used by later processing phases.

    The body is never accepted by the persistence port in this module.
    """

    metadata: SourceEmailCandidate
    sender_name: str | None
    sender_address: str | None
    body_content_type: str
    body_content: str

    def __repr__(self) -> str:
        return (
            "FetchedMail("
            f"graph_message_id={self.metadata.graph_message_id!r}, "
            f"content_type={self.body_content_type!r}, "
            f"has_attachments={self.metadata.has_attachments!r})"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MailIngestionResult:
    inserted: int
    updated: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MailSyncResult:
    observed: int
    inserted: int
    updated: int
    delta_link: str


class MailGateway(Protocol):
    """Read-only provider boundary for mailbox metadata and message bodies."""

    async def fetch_delta_page(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        cursor: str | None,
    ) -> MailDeltaPage: ...

    async def fetch_message(self, *, account_id: UUID, message_id: str) -> FetchedMail: ...


class MailSyncStore(Protocol):
    """Atomic persistence operations needed by the sync workflow."""

    async def begin_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        started_at: datetime,
    ) -> MailSyncState: ...

    async def complete_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        messages: tuple[SourceEmailCandidate, ...],
        delta_link: str,
        finished_at: datetime,
    ) -> MailIngestionResult: ...

    async def fail_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        error_code: str,
        finished_at: datetime,
    ) -> None: ...


class MailSyncService:
    """Follow delta pagination and commit metadata only after a complete round."""

    def __init__(
        self,
        *,
        gateway: MailGateway,
        store: MailSyncStore,
        clock: Clock,
        max_pages: int = 1_000,
    ) -> None:
        if max_pages < 1:
            msg = "max_pages must be positive"
            raise ValueError(msg)
        self._gateway = gateway
        self._store = store
        self._clock = clock
        self._max_pages = max_pages

    async def synchronize(self, *, account_id: UUID, folder_id: str) -> MailSyncResult:
        """Synchronize one folder without persisting message content."""
        state = await self._store.begin_sync(
            account_id=account_id,
            folder_id=folder_id,
            started_at=self._clock.now(),
        )
        cursor = state.delta_link
        messages: list[SourceEmailCandidate] = []
        visited_links: set[str] = set()

        try:
            for _ in range(self._max_pages):
                page = await self._gateway.fetch_delta_page(
                    account_id=account_id,
                    folder_id=folder_id,
                    cursor=cursor,
                )
                messages.extend(page.messages)

                if page.next_link is not None:
                    if page.next_link in visited_links:
                        raise DeltaStateInvalidError("delta pagination cycle detected")
                    visited_links.add(page.next_link)
                    cursor = page.next_link
                    continue

                if page.delta_link is None:
                    raise DeltaStateInvalidError("delta response did not include a terminal link")

                result = await self._store.complete_sync(
                    account_id=account_id,
                    folder_id=folder_id,
                    messages=tuple(messages),
                    delta_link=page.delta_link,
                    finished_at=self._clock.now(),
                )
                return MailSyncResult(
                    observed=len(messages),
                    inserted=result.inserted,
                    updated=result.updated,
                    delta_link=page.delta_link,
                )

            raise DeltaStateInvalidError("delta pagination exceeded the configured page limit")
        except ApplicationError as exc:
            await self._store.fail_sync(
                account_id=account_id,
                folder_id=folder_id,
                error_code=exc.code,
                finished_at=self._clock.now(),
            )
            raise
