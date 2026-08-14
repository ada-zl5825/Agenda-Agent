"""Phase 9A control-plane, queue, and safety regressions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from recruitment_agent.api.app import create_app
from recruitment_agent.application.errors import (
    OperationConflictError,
    OperationsAuthenticationError,
)
from recruitment_agent.application.operations import (
    SCHEDULED_PENDING_BATCH_LIMIT,
    ControlReason,
    OperationCreate,
    OperationExecutor,
    OperationsControlService,
    OperationSnapshot,
    OperationStatus,
    OperationType,
    RuntimeCapabilities,
    RuntimeControl,
    RuntimeControlDefaults,
    RuntimeControlPatch,
    scheduled_pending_drain_slot,
)
from recruitment_agent.operations.security import OperationsTokenAuthenticator

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)
ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000001")


class FixedClock:
    def now(self) -> datetime:
        return NOW


class RecordingQueue:
    def __init__(self) -> None:
        self.ids: list[UUID] = []

    async def enqueue(self, *, operation_id: UUID) -> None:
        self.ids.append(operation_id)


class ControlStore:
    def __init__(self, control: RuntimeControl) -> None:
        self.control = control
        self.operations: dict[UUID, OperationSnapshot] = {}
        self.by_key: dict[tuple[OperationType, str], UUID] = {}
        self.failed: list[tuple[UUID, str]] = []
        self.completed: list[tuple[UUID, dict[str, str | int | bool | None]]] = []
        self.released: list[UUID] = []
        self.cursor_resets = 0
        self.pending_ids: list[UUID] = []
        self.orphan_ids: list[UUID] = []

    async def ensure_control(self, **_kwargs: object) -> RuntimeControl:
        return self.control

    async def update_control(
        self,
        *,
        patch: RuntimeControlPatch,
        **_kwargs: object,
    ) -> RuntimeControl:
        if patch.expected_version != self.control.version:
            raise OperationConflictError("stale")
        self.control = replace(
            self.control,
            mail_sync_enabled=(
                self.control.mail_sync_enabled
                if patch.mail_sync_enabled is None
                else patch.mail_sync_enabled
            ),
            workflow_enabled=(
                self.control.workflow_enabled
                if patch.workflow_enabled is None
                else patch.workflow_enabled
            ),
            calendar_write_enabled=(
                self.control.calendar_write_enabled
                if patch.calendar_write_enabled is None
                else patch.calendar_write_enabled
            ),
            daily_brief_enabled=(
                self.control.daily_brief_enabled
                if patch.daily_brief_enabled is None
                else patch.daily_brief_enabled
            ),
            daily_brief_recipient=(
                self.control.daily_brief_recipient
                if patch.daily_brief_recipient is None
                else patch.daily_brief_recipient
            ),
            version=self.control.version + 1,
            reason=patch.reason,
        )
        return self.control

    async def create_operation(
        self,
        *,
        request: OperationCreate,
        requested_at: datetime,
    ) -> tuple[OperationSnapshot, bool]:
        key = (request.operation_type, request.idempotency_key_hash)
        existing_id = self.by_key.get(key)
        if existing_id is not None:
            return self.operations[existing_id], False
        operation = OperationSnapshot(
            id=uuid4(),
            account_id=request.account_id,
            operation_type=request.operation_type,
            status=OperationStatus.QUEUED,
            source_email_id=request.source_email_id,
            batch_limit=request.batch_limit,
            parent_operation_id=request.parent_operation_id,
            requested_at=requested_at,
            started_at=None,
            finished_at=None,
            attempt_count=0,
            result=None,
            error_code=None,
        )
        self.operations[operation.id] = operation
        self.by_key[key] = operation.id
        return operation, True

    async def get_operation(
        self, *, account_id: UUID, operation_id: UUID
    ) -> OperationSnapshot | None:
        operation = self.operations.get(operation_id)
        return operation if operation is not None and operation.account_id == account_id else None

    async def claim_operation(
        self,
        *,
        operation_id: UUID,
        **_kwargs: object,
    ) -> tuple[OperationSnapshot, bool]:
        operation = self.operations[operation_id]
        if operation.status is not OperationStatus.QUEUED:
            return operation, False
        operation = replace(
            operation,
            status=OperationStatus.RUNNING,
            started_at=NOW,
            attempt_count=operation.attempt_count + 1,
        )
        self.operations[operation_id] = operation
        return operation, True

    async def fail_operation(
        self, *, operation_id: UUID, error_code: str, **_kwargs: object
    ) -> None:
        self.failed.append((operation_id, error_code))

    async def complete_operation(
        self,
        *,
        operation_id: UUID,
        result: dict[str, str | int | bool | None],
        **_kwargs: object,
    ) -> None:
        self.completed.append((operation_id, result))

    async def release_operation_for_retry(
        self, *, operation_id: UUID, **_kwargs: object
    ) -> None:
        self.released.append(operation_id)

    async def reset_mail_cursor(self, **_kwargs: object) -> bool:
        self.cursor_resets += 1
        return True

    def _available_pending(self) -> list[UUID]:
        busy = {
            operation.source_email_id
            for operation in self.operations.values()
            if operation.operation_type is OperationType.PROCESS_EMAIL
            and operation.status in {OperationStatus.QUEUED, OperationStatus.RUNNING}
            and operation.source_email_id is not None
        }
        return [item for item in self.pending_ids if item not in busy]

    async def has_drainable_source_emails(self, *, account_id: UUID) -> bool:
        del account_id
        return bool(self.orphan_ids or self._available_pending())

    async def list_pending_source_email_ids(
        self,
        *,
        account_id: UUID,
        limit: int,
    ) -> tuple[UUID, ...]:
        del account_id
        return tuple(self._available_pending()[:limit])

    async def list_orphaned_needs_review_ids(
        self,
        *,
        account_id: UUID,
        limit: int,
    ) -> tuple[UUID, ...]:
        del account_id
        return tuple(self.orphan_ids[:limit])

    async def reclaim_orphaned_needs_review(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        now: datetime,
    ) -> bool:
        del account_id, now
        if source_email_id not in self.orphan_ids:
            return False
        self.orphan_ids.remove(source_email_id)
        if source_email_id not in self.pending_ids:
            self.pending_ids.append(source_email_id)
        return True

    async def count_child_operations(self, *, parent_operation_id: UUID) -> int:
        return sum(
            1
            for operation in self.operations.values()
            if operation.parent_operation_id == parent_operation_id
        )


def runtime_control(**changes: bool | str | None) -> RuntimeControl:
    values: dict[str, bool | str | None] = {
        "mail_sync_enabled": False,
        "workflow_enabled": False,
        "calendar_write_enabled": False,
        "daily_brief_enabled": False,
        "daily_brief_recipient": "brief@example.test",
    }
    values.update(changes)
    return RuntimeControl(
        account_id=ACCOUNT_ID,
        version=1,
        reason=ControlReason.TESTING,
        updated_by="test",
        updated_at=NOW,
        **values,
    )


def service(store: ControlStore, queue: RecordingQueue) -> OperationsControlService:
    return OperationsControlService(
        store=store,  # type: ignore[arg-type]
        queue=queue,
        clock=FixedClock(),
        account_id=ACCOUNT_ID,
        folder_id="inbox",
        defaults=RuntimeControlDefaults(
            mail_sync_enabled=False,
            workflow_enabled=False,
            calendar_write_enabled=False,
            daily_brief_enabled=False,
            daily_brief_recipient="brief@example.test",
        ),
        capabilities=RuntimeCapabilities(
            workflow_processing_available=True,
            calendar_write_available=True,
            daily_brief_available=True,
        ),
    )


@pytest.mark.asyncio
async def test_idempotent_submit_reuses_the_same_audited_operation() -> None:
    store = ControlStore(runtime_control())
    queue = RecordingQueue()

    first = await service(store, queue).submit(
        operation_type=OperationType.MAIL_SYNC,
        idempotency_key="stable-key-001",
    )
    second = await service(store, queue).submit(
        operation_type=OperationType.MAIL_SYNC,
        idempotency_key="stable-key-001",
    )

    assert second.id == first.id
    assert queue.ids == [first.id, first.id]
    assert "stable-key-001" not in repr(store.by_key)


@pytest.mark.asyncio
async def test_calendar_cannot_be_enabled_while_workflow_is_paused() -> None:
    store = ControlStore(runtime_control())

    with pytest.raises(OperationConflictError):
        await service(store, RecordingQueue()).update_control(
            RuntimeControlPatch(
                expected_version=1,
                reason=ControlReason.TESTING,
                calendar_write_enabled=True,
            )
        )


@pytest.mark.asyncio
async def test_daily_brief_cannot_be_enabled_without_a_runtime_recipient() -> None:
    store = ControlStore(runtime_control(daily_brief_recipient=None))

    with pytest.raises(OperationConflictError, match="recipient"):
        await service(store, RecordingQueue()).update_control(
            RuntimeControlPatch(
                expected_version=1,
                reason=ControlReason.TESTING,
                daily_brief_enabled=True,
            )
        )


@pytest.mark.asyncio
async def test_cursor_reset_fails_safely_until_sync_and_workflow_are_paused() -> None:
    store = ControlStore(runtime_control(mail_sync_enabled=True))
    operation, _ = await store.create_operation(
        request=OperationCreate(
            account_id=ACCOUNT_ID,
            operation_type=OperationType.RESET_MAIL_CURSOR,
            idempotency_key_hash="a" * 64,
        ),
        requested_at=NOW,
    )
    executor = OperationExecutor(
        store=store,  # type: ignore[arg-type]
        queue=RecordingQueue(),
        handlers=object(),  # type: ignore[arg-type]
        clock=FixedClock(),
        account_id=ACCOUNT_ID,
        folder_id="inbox",
        defaults=RuntimeControlDefaults(
            mail_sync_enabled=False,
            workflow_enabled=False,
            calendar_write_enabled=False,
            daily_brief_enabled=False,
            daily_brief_recipient="brief@example.test",
        ),
        capabilities=RuntimeCapabilities(
            workflow_processing_available=True,
            calendar_write_available=True,
            daily_brief_available=True,
        ),
    )

    await executor.execute(operation.id)

    assert store.cursor_resets == 0
    assert store.failed == [(operation.id, "OPERATION_CONFLICT")]


@pytest.mark.asyncio
async def test_manual_daily_brief_is_audited_and_respects_the_runtime_switch() -> None:
    class Handlers:
        def __init__(self) -> None:
            self.sends = 0

        async def send_daily_brief(self, *, recipient: str) -> bool:
            assert recipient == "brief@example.test"
            self.sends += 1
            return True

    store = ControlStore(runtime_control(daily_brief_enabled=True))
    operation, _ = await store.create_operation(
        request=OperationCreate(
            account_id=ACCOUNT_ID,
            operation_type=OperationType.SEND_DAILY_BRIEF,
            idempotency_key_hash="b" * 64,
        ),
        requested_at=NOW,
    )
    handlers = Handlers()
    executor = OperationExecutor(
        store=store,  # type: ignore[arg-type]
        queue=RecordingQueue(),
        handlers=handlers,  # type: ignore[arg-type]
        clock=FixedClock(),
        account_id=ACCOUNT_ID,
        folder_id="inbox",
        defaults=RuntimeControlDefaults(
            mail_sync_enabled=False,
            workflow_enabled=False,
            calendar_write_enabled=False,
            daily_brief_enabled=True,
            daily_brief_recipient="brief@example.test",
        ),
        capabilities=RuntimeCapabilities(
            workflow_processing_available=True,
            calendar_write_available=True,
            daily_brief_available=True,
        ),
    )

    await executor.execute(operation.id)

    assert handlers.sends == 1
    assert store.completed == [(operation.id, {"sent": True, "already_sent": False})]


@pytest.mark.asyncio
async def test_dispatch_job_executes_due_operations_as_a_queue_scale_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flex Consumption never scaled the queue worker, so the timer must execute."""
    import recruitment_agent.jobs.operations as jobs

    first, second = uuid4(), uuid4()
    executed: list[UUID] = []

    class FakeService:
        async def redispatch_queued(self) -> tuple[UUID, ...]:
            return (first, second)

    @asynccontextmanager
    async def fake_service() -> AsyncIterator[FakeService]:
        yield FakeService()

    async def fake_run_operation_job(
        operation_id: UUID, *, delivery_attempt: int = 1
    ) -> None:
        executed.append(operation_id)
        if operation_id == first:
            raise RuntimeError("one failing operation must not block the rest")

    monkeypatch.setattr(jobs, "operations_control_service", fake_service)
    monkeypatch.setattr(jobs, "run_operation_job", fake_run_operation_job)

    dispatched = await jobs.run_operation_dispatch_job()

    assert dispatched == 2
    assert executed == [first, second]


def _workflow_executor(store: ControlStore, queue: RecordingQueue) -> OperationExecutor:
    return OperationExecutor(
        store=store,  # type: ignore[arg-type]
        queue=queue,
        handlers=object(),  # type: ignore[arg-type]
        clock=FixedClock(),
        account_id=ACCOUNT_ID,
        folder_id="inbox",
        defaults=RuntimeControlDefaults(
            mail_sync_enabled=False,
            workflow_enabled=True,
            calendar_write_enabled=False,
            daily_brief_enabled=False,
            daily_brief_recipient="brief@example.test",
        ),
        capabilities=RuntimeCapabilities(
            workflow_processing_available=True,
            calendar_write_available=True,
            daily_brief_available=True,
        ),
    )


@pytest.mark.asyncio
async def test_process_pending_drains_every_waiting_email_in_batches() -> None:
    store = ControlStore(runtime_control(workflow_enabled=True))
    store.pending_ids = [uuid4() for _ in range(45)]
    operation, _ = await store.create_operation(
        request=OperationCreate(
            account_id=ACCOUNT_ID,
            operation_type=OperationType.PROCESS_PENDING,
            idempotency_key_hash="c" * 64,
            batch_limit=20,
        ),
        requested_at=NOW,
    )
    queue = RecordingQueue()

    await _workflow_executor(store, queue).execute(operation.id)

    children = [
        item
        for item in store.operations.values()
        if item.operation_type is OperationType.PROCESS_EMAIL
    ]
    assert len(children) == 45
    assert len(queue.ids) == 45
    assert store.completed == [
        (operation.id, {"queued": 45, "already_queued": 0, "continued": False})
    ]


@pytest.mark.asyncio
async def test_process_pending_skips_emails_already_queued_for_processing() -> None:
    store = ControlStore(runtime_control(workflow_enabled=True))
    waiting = uuid4()
    already = uuid4()
    store.pending_ids = [already, waiting]
    await store.create_operation(
        request=OperationCreate(
            account_id=ACCOUNT_ID,
            operation_type=OperationType.PROCESS_EMAIL,
            idempotency_key_hash="d" * 64,
            source_email_id=already,
        ),
        requested_at=NOW,
    )
    operation, _ = await store.create_operation(
        request=OperationCreate(
            account_id=ACCOUNT_ID,
            operation_type=OperationType.PROCESS_PENDING,
            idempotency_key_hash="e" * 64,
            batch_limit=20,
        ),
        requested_at=NOW,
    )
    queue = RecordingQueue()

    await _workflow_executor(store, queue).execute(operation.id)

    queued_children = [
        item
        for item in store.operations.values()
        if item.parent_operation_id == operation.id
    ]
    assert [item.source_email_id for item in queued_children] == [waiting]
    assert queue.ids == [queued_children[0].id]


@pytest.mark.asyncio
async def test_scheduled_pending_drain_submits_once_per_ten_minute_slot() -> None:
    store = ControlStore(runtime_control(workflow_enabled=True))
    store.pending_ids = [uuid4()]
    queue = RecordingQueue()
    control = service(store, queue)

    first = await control.submit_scheduled_pending_drain()
    second = await control.submit_scheduled_pending_drain()

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert first.batch_limit == SCHEDULED_PENDING_BATCH_LIMIT
    assert store.by_key[
        (
            OperationType.PROCESS_PENDING,
            control.hash_idempotency_key(f"auto-drain-{scheduled_pending_drain_slot(NOW)}"),
        )
    ] == first.id
    assert queue.ids == [first.id, first.id]


@pytest.mark.asyncio
async def test_scheduled_pending_drain_stays_idle_when_workflow_is_paused() -> None:
    store = ControlStore(runtime_control(workflow_enabled=False))
    store.pending_ids = [uuid4()]
    queue = RecordingQueue()

    assert await service(store, queue).submit_scheduled_pending_drain() is None
    assert queue.ids == []


@pytest.mark.asyncio
async def test_process_pending_enqueues_a_continuation_after_the_batch_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruitment_agent.application.operations.PENDING_DRAIN_MAX_BATCHES",
        2,
    )
    store = ControlStore(runtime_control(workflow_enabled=True))
    store.pending_ids = [uuid4() for _ in range(10)]
    operation, _ = await store.create_operation(
        request=OperationCreate(
            account_id=ACCOUNT_ID,
            operation_type=OperationType.PROCESS_PENDING,
            idempotency_key_hash="f" * 64,
            batch_limit=2,
        ),
        requested_at=NOW,
    )
    queue = RecordingQueue()

    await _workflow_executor(store, queue).execute(operation.id)

    continuations = [
        item
        for item in store.operations.values()
        if item.operation_type is OperationType.PROCESS_PENDING and item.id != operation.id
    ]
    assert len(continuations) == 1
    assert store.completed[0][1]["continued"] is True
    assert store.completed[0][1]["queued"] == 4


def test_operations_token_is_constant_contract_and_routes_are_exposed() -> None:
    authenticator = OperationsTokenAuthenticator("expected")
    authenticator.authenticate("expected")
    with pytest.raises(OperationsAuthenticationError):
        authenticator.authenticate("wrong")

    paths = set(create_app().openapi()["paths"])
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/api/v1/ops/status" in paths
    assert "/api/v1/ops/operations/mail-sync" in paths
    assert "/api/v1/ops/operations/process-pending" in paths
    assert "/api/v1/ops/operations/daily-brief" in paths
