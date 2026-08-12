"""Atomic, idempotent PostgreSQL mail metadata synchronization."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.application.mail_sync import MailIngestionResult
from recruitment_agent.domain.mail import (
    MailSyncState,
    MailSyncStatus,
    SourceEmailCandidate,
    SourceEmailProcessingStatus,
)
from recruitment_agent.persistence.models import MailSyncStateModel, SourceEmailModel


class SqlAlchemyMailSyncStore:
    """Advance the delta cursor only in the same transaction as metadata upserts."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def begin_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        started_at: datetime,
    ) -> MailSyncState:
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(MailSyncStateModel)
                .values(account_id=account_id, folder_id=folder_id)
                .on_conflict_do_nothing(index_elements=["account_id", "folder_id"])
            )
            model = await session.scalar(
                select(MailSyncStateModel)
                .where(
                    MailSyncStateModel.account_id == account_id,
                    MailSyncStateModel.folder_id == folder_id,
                )
                .with_for_update()
            )
            if model is None:
                raise RuntimeError("mail sync state could not be initialized")
            model.last_sync_started_at = started_at
            model.status = MailSyncStatus.SYNCING.value
            model.error_code = None
            return self._to_state(model)

    async def complete_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        messages: tuple[SourceEmailCandidate, ...],
        delta_link: str,
        finished_at: datetime,
    ) -> MailIngestionResult:
        unique_messages = {message.graph_message_id: message for message in messages}
        message_ids = tuple(unique_messages)
        async with self._session_factory.begin() as session:
            existing: set[str] = set()
            if message_ids:
                existing = set(
                    await session.scalars(
                        select(SourceEmailModel.graph_message_id).where(
                            SourceEmailModel.graph_message_id.in_(message_ids)
                        )
                    )
                )
            for message in unique_messages.values():
                statement = insert(SourceEmailModel).values(
                    account_id=account_id,
                    graph_message_id=message.graph_message_id,
                    internet_message_id=message.internet_message_id,
                    subject=message.subject,
                    sender_domain=message.sender_domain,
                    received_at=message.received_at,
                    outlook_web_link=message.outlook_web_link,
                    body_hash=message.body_hash,
                    has_attachments=message.has_attachments,
                    processing_status=SourceEmailProcessingStatus.PENDING.value,
                )
                excluded = statement.excluded
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["graph_message_id"],
                        set_={
                            "internet_message_id": excluded.internet_message_id,
                            "subject": excluded.subject,
                            "sender_domain": excluded.sender_domain,
                            "received_at": excluded.received_at,
                            "outlook_web_link": excluded.outlook_web_link,
                            "body_hash": func.coalesce(
                                excluded.body_hash,
                                SourceEmailModel.body_hash,
                            ),
                            "has_attachments": excluded.has_attachments,
                            "updated_at": func.now(),
                        },
                    )
                )
            result = await session.execute(
                update(MailSyncStateModel)
                .where(
                    MailSyncStateModel.account_id == account_id,
                    MailSyncStateModel.folder_id == folder_id,
                )
                .values(
                    delta_link=delta_link,
                    last_sync_finished_at=finished_at,
                    status=MailSyncStatus.SUCCEEDED.value,
                    error_code=None,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise RuntimeError("mail sync state disappeared during completion")
        inserted = len(message_ids) - len(existing)
        return MailIngestionResult(inserted=inserted, updated=len(existing))

    async def fail_sync(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        error_code: str,
        finished_at: datetime,
    ) -> None:
        async with self._session_factory.begin() as session:
            await session.execute(
                update(MailSyncStateModel)
                .where(
                    MailSyncStateModel.account_id == account_id,
                    MailSyncStateModel.folder_id == folder_id,
                )
                .values(
                    last_sync_finished_at=finished_at,
                    status=MailSyncStatus.FAILED.value,
                    error_code=error_code,
                )
            )

    @staticmethod
    def _to_state(model: MailSyncStateModel) -> MailSyncState:
        return MailSyncState(
            account_id=model.account_id,
            folder_id=model.folder_id,
            delta_link=model.delta_link,
            last_sync_started_at=model.last_sync_started_at,
            last_sync_finished_at=model.last_sync_finished_at,
            status=MailSyncStatus(model.status),
            error_code=model.error_code,
        )
