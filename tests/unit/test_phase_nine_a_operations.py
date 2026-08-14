"""Phase 9A control-plane, queue, and safety regressions."""

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
        self.released: list[UUID] = []
        self.cursor_resets = 0

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

    async def release_operation_for_retry(
        self, *, operation_id: UUID, **_kwargs: object
    ) -> None:
        self.released.append(operation_id)

    async def reset_mail_cursor(self, **_kwargs: object) -> bool:
        self.cursor_resets += 1
        return True


def runtime_control(**changes: bool) -> RuntimeControl:
    values = {
        "mail_sync_enabled": False,
        "workflow_enabled": False,
        "calendar_write_enabled": False,
        "daily_brief_enabled": False,
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
