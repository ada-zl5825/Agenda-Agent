"""PostgreSQL persistence for Phase 9A controls and operation audit."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute

from recruitment_agent.application.errors import OperationConflictError
from recruitment_agent.application.operations import (
    ControlReason,
    MailSyncStatusSnapshot,
    OperationCreate,
    OperationSnapshot,
    OperationsStatusSnapshot,
    OperationStatus,
    OperationType,
    ReadinessSnapshot,
    RuntimeCapabilities,
    RuntimeControl,
    RuntimeControlDefaults,
    RuntimeControlPatch,
    SafeOperationResult,
)
from recruitment_agent.domain.mail import MailSyncStatus, SourceEmailProcessingStatus
from recruitment_agent.persistence.models import (
    DailyBriefModel,
    MailSyncStateModel,
    MicrosoftConnectionModel,
    OperationRunModel,
    ProcessingRunModel,
    ReviewItemModel,
    RuntimeControlModel,
    SourceEmailModel,
)


class SqlAlchemyOperationsStore:
    """Atomic controls, leases, and privacy-safe operational projections."""

    _CONTROL_CONNECT_RETRY_DELAYS = (0.5, 1.0, 2.0)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_control(
        self,
        *,
        account_id: UUID,
        defaults: RuntimeControlDefaults,
        now: datetime,
    ) -> RuntimeControl:
        for delay in (*self._CONTROL_CONNECT_RETRY_DELAYS, None):
            try:
                return await self._ensure_control_once(
                    account_id=account_id,
                    defaults=defaults,
                    now=now,
                )
            except (InterfaceError, OperationalError):
                if delay is None:
                    raise
                await asyncio.sleep(delay)
        raise AssertionError("runtime control retry loop exhausted")

    async def _ensure_control_once(
        self,
        *,
        account_id: UUID,
        defaults: RuntimeControlDefaults,
        now: datetime,
    ) -> RuntimeControl:
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(RuntimeControlModel)
                .values(
                    account_id=account_id,
                    mail_sync_enabled=defaults.mail_sync_enabled,
                    workflow_enabled=defaults.workflow_enabled,
                    calendar_write_enabled=(
                        defaults.calendar_write_enabled and defaults.workflow_enabled
                    ),
                    daily_brief_enabled=defaults.daily_brief_enabled,
                    daily_brief_recipient=defaults.daily_brief_recipient,
                    version=1,
                    reason=ControlReason.MANUAL.value,
                    updated_by="bootstrap",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["account_id"])
            )
            # Read scalar columns eagerly so mapping cannot trigger implicit ORM I/O,
            # which raises MissingGreenlet in Azure Functions cold-start timers.
            row = (
                await session.execute(
                    select(
                        RuntimeControlModel.account_id,
                        RuntimeControlModel.mail_sync_enabled,
                        RuntimeControlModel.workflow_enabled,
                        RuntimeControlModel.calendar_write_enabled,
                        RuntimeControlModel.daily_brief_enabled,
                        RuntimeControlModel.daily_brief_recipient,
                        RuntimeControlModel.version,
                        RuntimeControlModel.reason,
                        RuntimeControlModel.updated_by,
                        RuntimeControlModel.updated_at,
                    ).where(RuntimeControlModel.account_id == account_id)
                )
            ).one_or_none()
            if row is None:
                raise RuntimeError("runtime control could not be initialized")
            if row.daily_brief_recipient is None and defaults.daily_brief_recipient is not None:
                await session.execute(
                    update(RuntimeControlModel)
                    .where(RuntimeControlModel.account_id == account_id)
                    .values(daily_brief_recipient=defaults.daily_brief_recipient)
                )
                return RuntimeControl(
                    account_id=row.account_id,
                    mail_sync_enabled=row.mail_sync_enabled,
                    workflow_enabled=row.workflow_enabled,
                    calendar_write_enabled=row.calendar_write_enabled,
                    daily_brief_enabled=row.daily_brief_enabled,
                    daily_brief_recipient=defaults.daily_brief_recipient,
                    version=row.version,
                    reason=ControlReason(row.reason),
                    updated_by=row.updated_by,
                    updated_at=row.updated_at,
                )
            return RuntimeControl(
                account_id=row.account_id,
                mail_sync_enabled=row.mail_sync_enabled,
                workflow_enabled=row.workflow_enabled,
                calendar_write_enabled=row.calendar_write_enabled,
                daily_brief_enabled=row.daily_brief_enabled,
                daily_brief_recipient=row.daily_brief_recipient,
                version=row.version,
                reason=ControlReason(row.reason),
                updated_by=row.updated_by,
                updated_at=row.updated_at,
            )

    async def update_control(
        self,
        *,
        account_id: UUID,
        patch: RuntimeControlPatch,
        updated_by: str,
        now: datetime,
    ) -> RuntimeControl:
        async with self._session_factory.begin() as session:
            model = await session.scalar(
                select(RuntimeControlModel)
                .where(RuntimeControlModel.account_id == account_id)
                .with_for_update()
            )
            if model is None:
                raise OperationConflictError("runtime control is not initialized")
            if model.version != patch.expected_version:
                raise OperationConflictError("runtime control version changed")
            if patch.mail_sync_enabled is not None:
                model.mail_sync_enabled = patch.mail_sync_enabled
            if patch.workflow_enabled is not None:
                model.workflow_enabled = patch.workflow_enabled
            if patch.calendar_write_enabled is not None:
                model.calendar_write_enabled = patch.calendar_write_enabled
            if patch.daily_brief_enabled is not None:
                model.daily_brief_enabled = patch.daily_brief_enabled
            if patch.daily_brief_recipient is not None:
                model.daily_brief_recipient = patch.daily_brief_recipient
            if model.calendar_write_enabled and not model.workflow_enabled:
                raise OperationConflictError("calendar writes require workflow processing")
            model.version += 1
            model.reason = patch.reason.value
            model.updated_by = updated_by
            model.updated_at = now
            await session.flush()
            return self._to_control(model)

    async def create_operation(
        self,
        *,
        request: OperationCreate,
        requested_at: datetime,
    ) -> tuple[OperationSnapshot, bool]:
        operation_id = uuid4()
        async with self._session_factory.begin() as session:
            inserted_id = await session.scalar(
                insert(OperationRunModel)
                .values(
                    id=operation_id,
                    account_id=request.account_id,
                    operation_type=request.operation_type.value,
                    status=OperationStatus.QUEUED.value,
                    idempotency_key_hash=request.idempotency_key_hash,
                    source_email_id=request.source_email_id,
                    batch_limit=request.batch_limit,
                    parent_operation_id=request.parent_operation_id,
                    requested_at=requested_at,
                    attempt_count=0,
                    created_at=requested_at,
                    updated_at=requested_at,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        "account_id",
                        "operation_type",
                        "idempotency_key_hash",
                    ]
                )
                .returning(OperationRunModel.id)
            )
            created = inserted_id is not None
            model = await session.scalar(
                select(OperationRunModel).where(
                    OperationRunModel.account_id == request.account_id,
                    OperationRunModel.operation_type == request.operation_type.value,
                    OperationRunModel.idempotency_key_hash
                    == request.idempotency_key_hash,
                )
            )
            if model is None:
                raise RuntimeError("operation could not be created")
            if (
                model.source_email_id != request.source_email_id
                or model.batch_limit != request.batch_limit
            ):
                raise OperationConflictError(
                    "Idempotency-Key was already used with different parameters"
                )
            return self._to_operation(model), created

    async def get_operation(
        self,
        *,
        account_id: UUID,
        operation_id: UUID,
    ) -> OperationSnapshot | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(OperationRunModel).where(
                    OperationRunModel.account_id == account_id,
                    OperationRunModel.id == operation_id,
                )
            )
            return None if model is None else self._to_operation(model)

    async def list_dispatchable_operation_ids(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[UUID, ...]:
        # Freshly submitted operations are given a short head start so the
        # low-latency queue worker can claim them before the dispatch timer
        # duplicates the enqueue and executes them inline.
        fresh_cutoff = now - timedelta(seconds=30)
        async with self._session_factory() as session:
            values = await session.scalars(
                select(OperationRunModel.id)
                .where(
                    (
                        (OperationRunModel.status == OperationStatus.QUEUED.value)
                        & (OperationRunModel.requested_at <= fresh_cutoff)
                    )
                    | (
                        (OperationRunModel.status == OperationStatus.RUNNING.value)
                        & (OperationRunModel.lease_expires_at < now)
                    )
                )
                .order_by(OperationRunModel.requested_at)
                .limit(limit)
            )
            return tuple(values)

    async def claim_operation(
        self,
        *,
        operation_id: UUID,
        now: datetime,
        lease_until: datetime,
    ) -> tuple[OperationSnapshot, bool]:
        async with self._session_factory.begin() as session:
            model = await session.scalar(
                update(OperationRunModel)
                .where(
                    OperationRunModel.id == operation_id,
                    (
                        (OperationRunModel.status == OperationStatus.QUEUED.value)
                        | (
                            (OperationRunModel.status == OperationStatus.RUNNING.value)
                            & (OperationRunModel.lease_expires_at < now)
                        )
                    ),
                )
                .values(
                    status=OperationStatus.RUNNING.value,
                    started_at=func.coalesce(OperationRunModel.started_at, now),
                    lease_expires_at=lease_until,
                    attempt_count=OperationRunModel.attempt_count + 1,
                    updated_at=now,
                )
                .returning(OperationRunModel)
            )
            if model is not None:
                return self._to_operation(model), True
            existing = await session.get(OperationRunModel, operation_id)
            if existing is None:
                raise RuntimeError("queued operation does not exist")
            return self._to_operation(existing), False

    async def complete_operation(
        self,
        *,
        operation_id: UUID,
        result: SafeOperationResult,
        finished_at: datetime,
    ) -> None:
        await self._finish_operation(
            operation_id=operation_id,
            status=OperationStatus.SUCCEEDED,
            result=result,
            error_code=None,
            finished_at=finished_at,
        )

    async def fail_operation(
        self,
        *,
        operation_id: UUID,
        error_code: str,
        finished_at: datetime,
    ) -> None:
        await self._finish_operation(
            operation_id=operation_id,
            status=OperationStatus.FAILED,
            result=None,
            error_code=error_code[:64],
            finished_at=finished_at,
        )

    async def release_operation_for_retry(
        self,
        *,
        operation_id: UUID,
        released_at: datetime,
    ) -> None:
        async with self._session_factory.begin() as session:
            await session.execute(
                update(OperationRunModel)
                .where(OperationRunModel.id == operation_id)
                .values(
                    status=OperationStatus.QUEUED.value,
                    lease_expires_at=None,
                    error_code=None,
                    updated_at=released_at,
                )
            )

    async def _finish_operation(
        self,
        *,
        operation_id: UUID,
        status: OperationStatus,
        result: SafeOperationResult | None,
        error_code: str | None,
        finished_at: datetime,
    ) -> None:
        async with self._session_factory.begin() as session:
            await session.execute(
                update(OperationRunModel)
                .where(OperationRunModel.id == operation_id)
                .values(
                    status=status.value,
                    result=result,
                    error_code=error_code,
                    finished_at=finished_at,
                    lease_expires_at=None,
                    updated_at=finished_at,
                )
            )

    async def read_status(
        self,
        *,
        account_id: UUID,
        control: RuntimeControl,
        capabilities: RuntimeCapabilities,
        folder_id: str,
    ) -> OperationsStatusSnapshot:
        async with self._session_factory() as session:
            connection = await session.get(MicrosoftConnectionModel, account_id)
            mail_state = await session.scalar(
                select(MailSyncStateModel).where(
                    MailSyncStateModel.account_id == account_id,
                    MailSyncStateModel.folder_id == folder_id,
                )
            )
            source_counts = await self._group_counts(
                session,
                SourceEmailModel.processing_status,
                SourceEmailModel.account_id == account_id,
            )
            workflow_counts = await self._group_counts(
                session,
                ProcessingRunModel.status,
                ProcessingRunModel.source_email_id == SourceEmailModel.id,
                SourceEmailModel.account_id == account_id,
            )
            operation_counts = await self._group_counts(
                session,
                OperationRunModel.status,
                OperationRunModel.account_id == account_id,
            )
            open_review_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ReviewItemModel)
                    .join(
                        ProcessingRunModel,
                        ProcessingRunModel.id == ReviewItemModel.processing_run_id,
                    )
                    .join(
                        SourceEmailModel,
                        SourceEmailModel.id == ProcessingRunModel.source_email_id,
                    )
                    .where(
                        SourceEmailModel.account_id == account_id,
                        ReviewItemModel.status == "open",
                    )
                )
                or 0
            )
            latest_brief = await session.scalar(
                select(DailyBriefModel)
                .where(DailyBriefModel.account_id == account_id)
                .order_by(DailyBriefModel.brief_date.desc())
                .limit(1)
            )
            return OperationsStatusSnapshot(
                control=control,
                capabilities=capabilities,
                oauth_authorized=(
                    connection is not None
                    and connection.token_cache_ciphertext is not None
                    and connection.home_account_id is not None
                ),
                mail_sync=MailSyncStatusSnapshot(
                    status=(None if mail_state is None else MailSyncStatus(mail_state.status)),
                    cursor_present=mail_state is not None and mail_state.delta_link is not None,
                    last_started_at=(
                        None if mail_state is None else mail_state.last_sync_started_at
                    ),
                    last_finished_at=(
                        None if mail_state is None else mail_state.last_sync_finished_at
                    ),
                    error_code=None if mail_state is None else mail_state.error_code,
                ),
                source_email_counts=source_counts,
                workflow_counts=workflow_counts,
                open_review_count=open_review_count,
                operation_counts=operation_counts,
                latest_brief_status=None if latest_brief is None else latest_brief.status,
                latest_brief_date=(
                    None if latest_brief is None else latest_brief.brief_date.isoformat()
                ),
            )

    async def read_readiness(self, *, account_id: UUID) -> ReadinessSnapshot:
        async with self._session_factory() as session:
            await session.scalar(select(1))
            connection = await session.get(MicrosoftConnectionModel, account_id)
            return ReadinessSnapshot(
                database_ready=True,
                oauth_authorized=(
                    connection is not None
                    and connection.token_cache_ciphertext is not None
                    and connection.home_account_id is not None
                ),
            )

    async def reset_mail_cursor(self, *, account_id: UUID, folder_id: str) -> bool:
        async with self._session_factory.begin() as session:
            result = await session.execute(
                update(MailSyncStateModel)
                .where(
                    MailSyncStateModel.account_id == account_id,
                    MailSyncStateModel.folder_id == folder_id,
                )
                .values(
                    delta_link=None,
                    status=MailSyncStatus.IDLE.value,
                    error_code=None,
                )
            )
            return getattr(result, "rowcount", 0) == 1

    async def claim_source_email(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        recover_existing: bool,
    ) -> bool:
        allowed_statuses = [SourceEmailProcessingStatus.PENDING.value]
        if recover_existing:
            allowed_statuses.extend(
                (
                    SourceEmailProcessingStatus.PROCESSING.value,
                    SourceEmailProcessingStatus.FAILED.value,
                )
            )
        async with self._session_factory.begin() as session:
            result = await session.execute(
                update(SourceEmailModel)
                .where(
                    SourceEmailModel.id == source_email_id,
                    SourceEmailModel.account_id == account_id,
                    SourceEmailModel.processing_status.in_(allowed_statuses),
                )
                .values(processing_status=SourceEmailProcessingStatus.PROCESSING.value)
            )
            return getattr(result, "rowcount", 0) == 1

    async def mark_source_email_failed(self, *, source_email_id: UUID) -> None:
        async with self._session_factory.begin() as session:
            await session.execute(
                update(SourceEmailModel)
                .where(SourceEmailModel.id == source_email_id)
                .values(processing_status=SourceEmailProcessingStatus.FAILED.value)
            )

    async def reset_source_email_pending(self, *, source_email_id: UUID) -> None:
        async with self._session_factory.begin() as session:
            await session.execute(
                update(SourceEmailModel)
                .where(
                    SourceEmailModel.id == source_email_id,
                    SourceEmailModel.processing_status.in_(
                        (
                            SourceEmailProcessingStatus.PROCESSING.value,
                            SourceEmailProcessingStatus.FAILED.value,
                        )
                    ),
                )
                .values(processing_status=SourceEmailProcessingStatus.PENDING.value)
            )

    async def list_pending_source_email_ids(
        self,
        *,
        account_id: UUID,
        limit: int,
    ) -> tuple[UUID, ...]:
        if limit <= 0:
            return ()
        async with self._session_factory() as session:
            values = await session.scalars(
                select(SourceEmailModel.id)
                .where(
                    SourceEmailModel.account_id == account_id,
                    SourceEmailModel.processing_status
                    == SourceEmailProcessingStatus.PENDING.value,
                )
                .order_by(SourceEmailModel.received_at)
                .limit(limit)
            )
            return tuple(values)

    async def list_orphaned_needs_review_ids(
        self,
        *,
        account_id: UUID,
        limit: int,
    ) -> tuple[UUID, ...]:
        if limit <= 0:
            return ()
        open_review = exists(
            select(ReviewItemModel.id).where(
                ReviewItemModel.processing_run_id == ProcessingRunModel.id,
                ReviewItemModel.status == "open",
            )
        )
        async with self._session_factory() as session:
            values = await session.scalars(
                select(SourceEmailModel.id)
                .join(
                    ProcessingRunModel,
                    ProcessingRunModel.source_email_id == SourceEmailModel.id,
                )
                .where(
                    SourceEmailModel.account_id == account_id,
                    SourceEmailModel.processing_status
                    == SourceEmailProcessingStatus.NEEDS_REVIEW.value,
                    ProcessingRunModel.status == "needs_review",
                    ~open_review,
                )
                .order_by(SourceEmailModel.received_at)
                .limit(limit)
            )
            return tuple(dict.fromkeys(values))

    async def reclaim_orphaned_needs_review(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        now: datetime,
    ) -> bool:
        open_review = exists(
            select(ReviewItemModel.id).where(
                ReviewItemModel.processing_run_id == ProcessingRunModel.id,
                ReviewItemModel.status == "open",
            )
        )
        async with self._session_factory.begin() as session:
            run = await session.scalar(
                select(ProcessingRunModel)
                .join(
                    SourceEmailModel,
                    SourceEmailModel.id == ProcessingRunModel.source_email_id,
                )
                .where(
                    SourceEmailModel.id == source_email_id,
                    SourceEmailModel.account_id == account_id,
                    SourceEmailModel.processing_status
                    == SourceEmailProcessingStatus.NEEDS_REVIEW.value,
                    ProcessingRunModel.status == "needs_review",
                    ~open_review,
                )
                .order_by(ProcessingRunModel.started_at.desc())
                .limit(1)
            )
            if run is None:
                return False
            run.status = "failed"
            run.error_code = "ORPHANED_REVIEW"
            run.finished_at = now
            await session.execute(
                update(SourceEmailModel)
                .where(
                    SourceEmailModel.id == source_email_id,
                    SourceEmailModel.account_id == account_id,
                    SourceEmailModel.processing_status
                    == SourceEmailProcessingStatus.NEEDS_REVIEW.value,
                )
                .values(processing_status=SourceEmailProcessingStatus.PENDING.value)
            )
            return True

    async def count_child_operations(self, *, parent_operation_id: UUID) -> int:
        async with self._session_factory() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(OperationRunModel)
                    .where(OperationRunModel.parent_operation_id == parent_operation_id)
                )
                or 0
            )

    @staticmethod
    async def _group_counts(
        session: AsyncSession,
        group_column: InstrumentedAttribute[str],
        *conditions: ColumnElement[bool],
    ) -> dict[str, int]:
        rows = await session.execute(
            select(group_column, func.count()).where(*conditions).group_by(group_column)
        )
        return {str(key): int(count) for key, count in rows}

    @staticmethod
    def _to_control(model: RuntimeControlModel) -> RuntimeControl:
        return RuntimeControl(
            account_id=model.account_id,
            mail_sync_enabled=model.mail_sync_enabled,
            workflow_enabled=model.workflow_enabled,
            calendar_write_enabled=model.calendar_write_enabled,
            daily_brief_enabled=model.daily_brief_enabled,
            daily_brief_recipient=model.daily_brief_recipient,
            version=model.version,
            reason=ControlReason(model.reason),
            updated_by=model.updated_by,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _to_operation(model: OperationRunModel) -> OperationSnapshot:
        result = model.result
        return OperationSnapshot(
            id=model.id,
            account_id=model.account_id,
            operation_type=OperationType(model.operation_type),
            status=OperationStatus(model.status),
            source_email_id=model.source_email_id,
            batch_limit=model.batch_limit,
            parent_operation_id=model.parent_operation_id,
            requested_at=model.requested_at,
            started_at=model.started_at,
            finished_at=model.finished_at,
            attempt_count=model.attempt_count,
            result=result,  # type: ignore[arg-type]
            error_code=model.error_code,
        )
