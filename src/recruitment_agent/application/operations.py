"""Phase 9A runtime control and asynchronous operation orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid5

from recruitment_agent.application.errors import (
    OperationConflictError,
    OperationDisabledError,
    OperationNotFoundError,
)
from recruitment_agent.application.mail_sync import MailSyncResult
from recruitment_agent.domain.mail import MailSyncStatus
from recruitment_agent.domain.ports import Clock
from recruitment_agent.domain.recipient import normalize_recipient_address
from recruitment_agent.domain.time import require_aware, require_optional_aware

SafeResultValue = str | int | bool | None
SafeOperationResult = dict[str, SafeResultValue]


class ControlReason(StrEnum):
    MANUAL = "manual"
    TESTING = "testing"
    MAINTENANCE = "maintenance"
    INCIDENT = "incident"
    ACCOUNT_SWITCH = "account_switch"


class OperationType(StrEnum):
    MAIL_SYNC = "mail_sync"
    PROCESS_EMAIL = "process_email"
    PROCESS_PENDING = "process_pending"
    RESET_MAIL_CURSOR = "reset_mail_cursor"
    SEND_DAILY_BRIEF = "send_daily_brief"


class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


SCHEDULED_PENDING_BATCH_LIMIT = 20
PENDING_DRAIN_MAX_BATCHES = 50


def scheduled_pending_drain_slot(now: datetime) -> str:
    """Stable 10-minute UTC slot used as the scheduled drain idempotency key."""
    require_aware(now, field_name="now")
    aligned = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
    return aligned.strftime("%Y%m%d%H%M")


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeControlDefaults:
    mail_sync_enabled: bool
    workflow_enabled: bool
    calendar_write_enabled: bool
    daily_brief_enabled: bool
    daily_brief_recipient: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeCapabilities:
    workflow_processing_available: bool
    calendar_write_available: bool
    daily_brief_available: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeControl:
    account_id: UUID
    mail_sync_enabled: bool
    workflow_enabled: bool
    calendar_write_enabled: bool
    daily_brief_enabled: bool
    daily_brief_recipient: str | None
    version: int
    reason: ControlReason
    updated_by: str
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("runtime control version must be positive")
        if self.calendar_write_enabled and not self.workflow_enabled:
            raise ValueError("calendar writes require workflow processing")
        if not self.updated_by.strip():
            raise ValueError("runtime control actor must not be empty")
        if self.daily_brief_recipient is not None and (
            normalize_recipient_address(self.daily_brief_recipient)
            != self.daily_brief_recipient
        ):
            raise ValueError("Daily Brief recipient must be normalized")
        require_aware(self.updated_at, field_name="updated_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeControlPatch:
    expected_version: int
    reason: ControlReason
    mail_sync_enabled: bool | None = None
    workflow_enabled: bool | None = None
    calendar_write_enabled: bool | None = None
    daily_brief_enabled: bool | None = None
    daily_brief_recipient: str | None = None

    def __post_init__(self) -> None:
        if self.expected_version < 1:
            raise ValueError("expected runtime control version must be positive")
        if all(
            value is None
            for value in (
                self.mail_sync_enabled,
                self.workflow_enabled,
                self.calendar_write_enabled,
                self.daily_brief_enabled,
                self.daily_brief_recipient,
            )
        ):
            raise ValueError("runtime control patch must change at least one switch")
        if self.daily_brief_recipient is not None and (
            normalize_recipient_address(self.daily_brief_recipient)
            != self.daily_brief_recipient
        ):
            raise ValueError("Daily Brief recipient must be normalized")


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationCreate:
    account_id: UUID
    operation_type: OperationType
    idempotency_key_hash: str
    source_email_id: UUID | None = None
    batch_limit: int | None = None
    parent_operation_id: UUID | None = None

    def __post_init__(self) -> None:
        if len(self.idempotency_key_hash) != 64:
            raise ValueError("operation idempotency hash must be SHA-256")
        if self.operation_type is OperationType.PROCESS_EMAIL:
            if self.source_email_id is None or self.batch_limit is not None:
                raise ValueError("process-email operation requires exactly one source email")
        elif self.operation_type is OperationType.PROCESS_PENDING:
            if self.batch_limit is None or not 1 <= self.batch_limit <= 100:
                raise ValueError("process-pending operation requires a bounded batch")
            if self.source_email_id is not None:
                raise ValueError("process-pending operation cannot target one email")
        elif self.source_email_id is not None or self.batch_limit is not None:
            raise ValueError("operation does not accept email targets")


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationSnapshot:
    id: UUID
    account_id: UUID
    operation_type: OperationType
    status: OperationStatus
    source_email_id: UUID | None
    batch_limit: int | None
    parent_operation_id: UUID | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    result: SafeOperationResult | None
    error_code: str | None

    def __post_init__(self) -> None:
        require_aware(self.requested_at, field_name="requested_at")
        require_optional_aware(self.started_at, field_name="started_at")
        require_optional_aware(self.finished_at, field_name="finished_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class MailSyncStatusSnapshot:
    status: MailSyncStatus | None
    cursor_present: bool
    last_started_at: datetime | None
    last_finished_at: datetime | None
    error_code: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationsStatusSnapshot:
    control: RuntimeControl
    capabilities: RuntimeCapabilities
    oauth_authorized: bool
    mail_sync: MailSyncStatusSnapshot
    source_email_counts: dict[str, int]
    workflow_counts: dict[str, int]
    open_review_count: int
    operation_counts: dict[str, int]
    latest_brief_status: str | None
    latest_brief_date: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadinessSnapshot:
    database_ready: bool
    oauth_authorized: bool

    @property
    def ready(self) -> bool:
        return self.database_ready and self.oauth_authorized


class OperationsStore(Protocol):
    async def ensure_control(
        self,
        *,
        account_id: UUID,
        defaults: RuntimeControlDefaults,
        now: datetime,
    ) -> RuntimeControl: ...

    async def update_control(
        self,
        *,
        account_id: UUID,
        patch: RuntimeControlPatch,
        updated_by: str,
        now: datetime,
    ) -> RuntimeControl: ...

    async def create_operation(
        self,
        *,
        request: OperationCreate,
        requested_at: datetime,
    ) -> tuple[OperationSnapshot, bool]: ...

    async def get_operation(
        self,
        *,
        account_id: UUID,
        operation_id: UUID,
    ) -> OperationSnapshot | None: ...

    async def list_dispatchable_operation_ids(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[UUID, ...]: ...

    async def claim_operation(
        self,
        *,
        operation_id: UUID,
        now: datetime,
        lease_until: datetime,
    ) -> tuple[OperationSnapshot, bool]: ...

    async def complete_operation(
        self,
        *,
        operation_id: UUID,
        result: SafeOperationResult,
        finished_at: datetime,
    ) -> None: ...

    async def fail_operation(
        self,
        *,
        operation_id: UUID,
        error_code: str,
        finished_at: datetime,
    ) -> None: ...

    async def release_operation_for_retry(
        self,
        *,
        operation_id: UUID,
        released_at: datetime,
    ) -> None: ...

    async def read_status(
        self,
        *,
        account_id: UUID,
        control: RuntimeControl,
        capabilities: RuntimeCapabilities,
        folder_id: str,
    ) -> OperationsStatusSnapshot: ...

    async def read_readiness(self, *, account_id: UUID) -> ReadinessSnapshot: ...

    async def reset_mail_cursor(
        self,
        *,
        account_id: UUID,
        folder_id: str,
    ) -> bool: ...

    async def claim_source_email(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        recover_existing: bool,
    ) -> bool: ...

    async def mark_source_email_failed(self, *, source_email_id: UUID) -> None: ...

    async def reset_source_email_pending(self, *, source_email_id: UUID) -> None: ...

    async def list_pending_source_email_ids(
        self,
        *,
        account_id: UUID,
        limit: int,
    ) -> tuple[UUID, ...]: ...

    async def list_orphaned_needs_review_ids(
        self,
        *,
        account_id: UUID,
        limit: int,
    ) -> tuple[UUID, ...]: ...

    async def reclaim_orphaned_needs_review(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        now: datetime,
    ) -> bool: ...

    async def count_child_operations(self, *, parent_operation_id: UUID) -> int: ...

    async def has_drainable_source_emails(self, *, account_id: UUID) -> bool: ...


class OperationQueue(Protocol):
    async def enqueue(self, *, operation_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowOperationResult:
    status: str
    interrupted: bool


class OperationHandlers(Protocol):
    async def synchronize_mail(self) -> MailSyncResult: ...

    async def send_daily_brief(self, *, recipient: str) -> bool: ...

    async def process_email(
        self,
        *,
        source_email_id: UUID,
        processing_run_id: UUID,
        calendar_write_enabled: bool,
    ) -> WorkflowOperationResult: ...


class OperationsControlService:
    """Validated control-plane commands used by the HTTP adapter."""

    def __init__(
        self,
        *,
        store: OperationsStore,
        queue: OperationQueue,
        clock: Clock,
        account_id: UUID,
        folder_id: str,
        defaults: RuntimeControlDefaults,
        capabilities: RuntimeCapabilities,
    ) -> None:
        self._store = store
        self._queue = queue
        self._clock = clock
        self._account_id = account_id
        self._folder_id = folder_id
        self._defaults = defaults
        self._capabilities = capabilities

    async def get_control(self) -> RuntimeControl:
        return await self._store.ensure_control(
            account_id=self._account_id,
            defaults=self._defaults,
            now=self._clock.now(),
        )

    async def update_control(
        self,
        patch: RuntimeControlPatch,
        *,
        updated_by: str = "ops_api",
    ) -> RuntimeControl:
        current = await self.get_control()
        workflow_enabled = (
            current.workflow_enabled
            if patch.workflow_enabled is None
            else patch.workflow_enabled
        )
        calendar_enabled = (
            current.calendar_write_enabled
            if patch.calendar_write_enabled is None
            else patch.calendar_write_enabled
        )
        if calendar_enabled and not workflow_enabled:
            raise OperationConflictError("calendar writes require workflow processing")
        if patch.workflow_enabled is True and not (
            self._capabilities.workflow_processing_available
        ):
            raise OperationConflictError("workflow processing is not configured")
        if patch.calendar_write_enabled is True and not (
            self._capabilities.calendar_write_available
        ):
            raise OperationConflictError("calendar writes are not configured in this deployment")
        if patch.daily_brief_enabled is True and not self._capabilities.daily_brief_available:
            raise OperationConflictError("Daily Brief is not configured in this deployment")
        effective_recipient = (
            current.daily_brief_recipient
            if patch.daily_brief_recipient is None
            else patch.daily_brief_recipient
        )
        if patch.daily_brief_enabled is True and effective_recipient is None:
            raise OperationConflictError("Daily Brief recipient is not configured")
        return await self._store.update_control(
            account_id=self._account_id,
            patch=patch,
            updated_by=updated_by,
            now=self._clock.now(),
        )

    async def get_status(self) -> OperationsStatusSnapshot:
        control = await self.get_control()
        return await self._store.read_status(
            account_id=self._account_id,
            control=control,
            capabilities=self._capabilities,
            folder_id=self._folder_id,
        )

    async def get_readiness(self) -> ReadinessSnapshot:
        try:
            return await self._store.read_readiness(account_id=self._account_id)
        except Exception:
            return ReadinessSnapshot(database_ready=False, oauth_authorized=False)

    async def submit(
        self,
        *,
        operation_type: OperationType,
        idempotency_key: str,
        source_email_id: UUID | None = None,
        batch_limit: int | None = None,
    ) -> OperationSnapshot:
        key_hash = self.hash_idempotency_key(idempotency_key)
        operation, _created = await self._store.create_operation(
            request=OperationCreate(
                account_id=self._account_id,
                operation_type=operation_type,
                idempotency_key_hash=key_hash,
                source_email_id=source_email_id,
                batch_limit=batch_limit,
            ),
            requested_at=self._clock.now(),
        )
        if operation.status is OperationStatus.QUEUED:
            await self._queue.enqueue(operation_id=operation.id)
        return operation

    async def get_operation(self, operation_id: UUID) -> OperationSnapshot:
        operation = await self._store.get_operation(
            account_id=self._account_id,
            operation_id=operation_id,
        )
        if operation is None:
            raise OperationNotFoundError("operation does not exist")
        return operation

    async def redispatch_queued(self, *, limit: int = 100) -> tuple[UUID, ...]:
        operation_ids = await self._store.list_dispatchable_operation_ids(
            now=self._clock.now(),
            limit=limit,
        )
        for operation_id in operation_ids:
            await self._queue.enqueue(operation_id=operation_id)
        return operation_ids

    async def submit_scheduled_pending_drain(self) -> OperationSnapshot | None:
        """Queue one bounded drain when workflow is on and mail is waiting."""
        if not self._capabilities.workflow_processing_available:
            return None
        control = await self.get_control()
        if not control.workflow_enabled:
            return None
        if not await self._store.has_drainable_source_emails(account_id=self._account_id):
            return None
        slot = scheduled_pending_drain_slot(self._clock.now())
        return await self.submit(
            operation_type=OperationType.PROCESS_PENDING,
            idempotency_key=f"auto-drain-{slot}",
            batch_limit=SCHEDULED_PENDING_BATCH_LIMIT,
        )

    @staticmethod
    def hash_idempotency_key(value: str) -> str:
        normalized = value.strip()
        if not 8 <= len(normalized) <= 128 or not normalized.isascii():
            raise ValueError("Idempotency-Key must be 8-128 ASCII characters")
        return hashlib.sha256(normalized.encode("ascii")).hexdigest()


class OperationExecutor:
    """Execute one queued command with leases and deterministic child fan-out."""

    _LEASE = timedelta(minutes=25)
    _PROCESSING_RUN_NAMESPACE = UUID("16ad8019-7838-4a3c-9a8c-824cd8c99a9e")

    def __init__(
        self,
        *,
        store: OperationsStore,
        queue: OperationQueue,
        handlers: OperationHandlers,
        clock: Clock,
        account_id: UUID,
        folder_id: str,
        defaults: RuntimeControlDefaults,
        capabilities: RuntimeCapabilities,
    ) -> None:
        self._store = store
        self._queue = queue
        self._handlers = handlers
        self._clock = clock
        self._account_id = account_id
        self._folder_id = folder_id
        self._defaults = defaults
        self._capabilities = capabilities

    async def execute(self, operation_id: UUID, *, delivery_attempt: int = 1) -> None:
        now = self._clock.now()
        operation, claimed = await self._store.claim_operation(
            operation_id=operation_id,
            now=now,
            lease_until=now + self._LEASE,
        )
        if not claimed:
            return
        if operation.account_id != self._account_id:
            await self._store.fail_operation(
                operation_id=operation.id,
                error_code="OPERATION_ACCOUNT_MISMATCH",
                finished_at=self._clock.now(),
            )
            return
        attempt = max(delivery_attempt, operation.attempt_count)
        try:
            control = await self._store.ensure_control(
                account_id=self._account_id,
                defaults=self._defaults,
                now=now,
            )
            result = await self._execute_claimed(operation, control)
        except (OperationDisabledError, OperationConflictError) as exc:
            error_code = getattr(exc, "code", "OPERATION_FAILED")
            await self._store.fail_operation(
                operation_id=operation.id,
                error_code=str(error_code),
                finished_at=self._clock.now(),
            )
            return
        except Exception as exc:
            if operation.source_email_id is not None and attempt < 5:
                await self._store.reset_source_email_pending(
                    source_email_id=operation.source_email_id
                )
            if attempt < 5:
                await self._store.release_operation_for_retry(
                    operation_id=operation.id,
                    released_at=self._clock.now(),
                )
                raise
            if operation.source_email_id is not None:
                await self._store.mark_source_email_failed(
                    source_email_id=operation.source_email_id
                )
            error_code = getattr(exc, "code", "OPERATION_FAILED")
            await self._store.fail_operation(
                operation_id=operation.id,
                error_code=str(error_code),
                finished_at=self._clock.now(),
            )
            return
        await self._store.complete_operation(
            operation_id=operation.id,
            result=result,
            finished_at=self._clock.now(),
        )

    async def _execute_claimed(
        self,
        operation: OperationSnapshot,
        control: RuntimeControl,
    ) -> SafeOperationResult:
        if operation.operation_type is OperationType.MAIL_SYNC:
            if not control.mail_sync_enabled:
                raise OperationDisabledError("mail synchronization is paused")
            result = await self._handlers.synchronize_mail()
            return {
                "observed": result.observed,
                "inserted": result.inserted,
                "updated": result.updated,
            }
        if operation.operation_type is OperationType.RESET_MAIL_CURSOR:
            if control.mail_sync_enabled or control.workflow_enabled:
                raise OperationConflictError(
                    "pause mail synchronization and workflow before resetting the cursor"
                )
            reset = await self._store.reset_mail_cursor(
                account_id=self._account_id,
                folder_id=self._folder_id,
            )
            return {"cursor_reset": reset}
        if operation.operation_type is OperationType.SEND_DAILY_BRIEF:
            if not control.daily_brief_enabled:
                raise OperationDisabledError("Daily Brief delivery is paused")
            if not self._capabilities.daily_brief_available:
                raise OperationDisabledError("Daily Brief delivery is not configured")
            if control.daily_brief_recipient is None:
                raise OperationDisabledError("Daily Brief recipient is not configured")
            sent = await self._handlers.send_daily_brief(
                recipient=control.daily_brief_recipient,
            )
            return {"sent": sent, "already_sent": not sent}
        if operation.operation_type is OperationType.PROCESS_PENDING:
            if not control.workflow_enabled:
                raise OperationDisabledError("workflow processing is paused")
            if not self._capabilities.workflow_processing_available:
                raise OperationDisabledError("workflow processing is not configured")
            return await self._fan_out_pending(operation)
        if operation.operation_type is OperationType.PROCESS_EMAIL:
            if not control.workflow_enabled:
                raise OperationDisabledError("workflow processing is paused")
            if not self._capabilities.workflow_processing_available:
                raise OperationDisabledError("workflow processing is not configured")
            return await self._process_email(operation, control)
        raise ValueError("unsupported operation type")

    async def _fan_out_pending(self, operation: OperationSnapshot) -> SafeOperationResult:
        assert operation.batch_limit is not None
        existing = await self._store.count_child_operations(
            parent_operation_id=operation.id
        )
        queued = 0
        batches = 0
        while batches < PENDING_DRAIN_MAX_BATCHES:
            source_ids = await self._next_pending_batch(operation.batch_limit)
            if not source_ids:
                break
            queued += await self._enqueue_process_email_children(operation, source_ids)
            batches += 1
            if len(source_ids) < operation.batch_limit:
                break
        continued = False
        if batches >= PENDING_DRAIN_MAX_BATCHES and await self._store.has_drainable_source_emails(
            account_id=self._account_id
        ):
            continued = await self._enqueue_pending_continuation(operation)
        return {
            "queued": queued,
            "already_queued": existing,
            "continued": continued,
        }

    async def _next_pending_batch(self, limit: int) -> tuple[UUID, ...]:
        orphans = await self._store.list_orphaned_needs_review_ids(
            account_id=self._account_id,
            limit=limit,
        )
        for source_email_id in orphans:
            await self._store.reclaim_orphaned_needs_review(
                account_id=self._account_id,
                source_email_id=source_email_id,
                now=self._clock.now(),
            )
        return await self._store.list_pending_source_email_ids(
            account_id=self._account_id,
            limit=limit,
        )

    async def _enqueue_process_email_children(
        self,
        operation: OperationSnapshot,
        source_ids: tuple[UUID, ...],
    ) -> int:
        queued = 0
        for source_email_id in source_ids:
            key_hash = hashlib.sha256(
                f"{operation.id}:{source_email_id}".encode()
            ).hexdigest()
            child, _created = await self._store.create_operation(
                request=OperationCreate(
                    account_id=self._account_id,
                    operation_type=OperationType.PROCESS_EMAIL,
                    idempotency_key_hash=key_hash,
                    source_email_id=source_email_id,
                    parent_operation_id=operation.id,
                ),
                requested_at=self._clock.now(),
            )
            if child.status is OperationStatus.QUEUED:
                await self._queue.enqueue(operation_id=child.id)
                queued += 1
        return queued

    async def _enqueue_pending_continuation(self, operation: OperationSnapshot) -> bool:
        assert operation.batch_limit is not None
        continuation, created = await self._store.create_operation(
            request=OperationCreate(
                account_id=self._account_id,
                operation_type=OperationType.PROCESS_PENDING,
                idempotency_key_hash=OperationsControlService.hash_idempotency_key(
                    f"continue-{operation.id}"
                ),
                batch_limit=operation.batch_limit,
            ),
            requested_at=self._clock.now(),
        )
        if continuation.status is OperationStatus.QUEUED:
            await self._queue.enqueue(operation_id=continuation.id)
        return created or continuation.status is OperationStatus.QUEUED

    async def _process_email(
        self,
        operation: OperationSnapshot,
        control: RuntimeControl,
    ) -> SafeOperationResult:
        assert operation.source_email_id is not None
        claimed = await self._store.claim_source_email(
            account_id=self._account_id,
            source_email_id=operation.source_email_id,
            recover_existing=operation.attempt_count > 1,
        )
        if not claimed:
            return {"skipped": True, "reason": "source_not_pending"}
        processing_run_id = uuid5(
            self._PROCESSING_RUN_NAMESPACE,
            str(operation.id),
        )
        outcome = await self._handlers.process_email(
            source_email_id=operation.source_email_id,
            processing_run_id=processing_run_id,
            calendar_write_enabled=(
                control.calendar_write_enabled
                and self._capabilities.calendar_write_available
            ),
        )
        return {
            "workflow_status": outcome.status,
            "interrupted": outcome.interrupted,
        }
