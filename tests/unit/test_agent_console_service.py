from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from recruitment_agent.application.agent_console import (
    AgentConsoleService,
    AgentControlCommand,
    AgentControlSwitch,
    AgentManualAction,
    AgentOperationCommand,
    DailyBriefRecipientCommand,
)
from recruitment_agent.application.errors import (
    OperationConflictError,
    ReviewAccessDeniedError,
)
from recruitment_agent.application.operations import (
    ControlReason,
    MailSyncStatusSnapshot,
    OperationSnapshot,
    OperationsStatusSnapshot,
    OperationStatus,
    OperationType,
    ReadinessSnapshot,
    RuntimeCapabilities,
    RuntimeControl,
    RuntimeControlPatch,
)

NOW = datetime(2026, 8, 14, 8, tzinfo=UTC)


def _control(account_id: UUID) -> RuntimeControl:
    return RuntimeControl(
        account_id=account_id,
        mail_sync_enabled=True,
        workflow_enabled=True,
        calendar_write_enabled=False,
        daily_brief_enabled=True,
        daily_brief_recipient="old@example.test",
        version=5,
        reason=ControlReason.MANUAL,
        updated_by="test",
        updated_at=NOW,
    )


class Operations:
    def __init__(self, account_id: UUID) -> None:
        self.control = _control(account_id)
        self.patches: list[tuple[RuntimeControlPatch, str]] = []
        self.submissions: list[dict[str, object]] = []

    async def get_control(self) -> RuntimeControl:
        return self.control

    async def get_readiness(self) -> ReadinessSnapshot:
        return ReadinessSnapshot(database_ready=True, oauth_authorized=True)

    async def get_status(self) -> OperationsStatusSnapshot:
        return OperationsStatusSnapshot(
            control=self.control,
            capabilities=RuntimeCapabilities(
                workflow_processing_available=True,
                calendar_write_available=True,
                daily_brief_available=True,
            ),
            oauth_authorized=True,
            mail_sync=MailSyncStatusSnapshot(
                status=None,
                cursor_present=False,
                last_started_at=None,
                last_finished_at=None,
                error_code=None,
            ),
            source_email_counts={},
            workflow_counts={},
            open_review_count=0,
            operation_counts={},
            latest_brief_status=None,
            latest_brief_date=None,
        )

    async def get_operation(self, operation_id: UUID) -> OperationSnapshot:
        return OperationSnapshot(
            id=operation_id,
            account_id=self.control.account_id,
            operation_type=OperationType.MAIL_SYNC,
            status=OperationStatus.QUEUED,
            source_email_id=None,
            batch_limit=None,
            parent_operation_id=None,
            requested_at=NOW,
            started_at=None,
            finished_at=None,
            attempt_count=0,
            result=None,
            error_code=None,
        )

    async def update_control(
        self,
        patch: RuntimeControlPatch,
        *,
        updated_by: str,
    ) -> RuntimeControl:
        self.patches.append((patch, updated_by))
        self.control = replace(
            self.control,
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
        )
        return self.control

    async def submit(self, **kwargs: object) -> OperationSnapshot:
        self.submissions.append(kwargs)
        return await self.get_operation(uuid4())


@pytest.mark.asyncio
async def test_console_scopes_status_and_mutations_to_the_signed_account() -> None:
    account_id = uuid4()
    operations = Operations(account_id)
    service = AgentConsoleService(operations)  # type: ignore[arg-type]

    snapshot = await service.get_snapshot(account_id=account_id)
    updated = await service.update_control(
        account_id=account_id,
        command=AgentControlCommand(
            switch=AgentControlSwitch.DAILY_BRIEF,
            enabled=False,
            expected_version=5,
        ),
    )

    assert snapshot.readiness.ready
    assert updated.daily_brief_enabled is False
    patch, actor = operations.patches[0]
    assert patch.daily_brief_enabled is False
    assert actor == "web_console"
    with pytest.raises(ReviewAccessDeniedError):
        await service.get_snapshot(account_id=uuid4())


@pytest.mark.asyncio
async def test_console_updates_normalized_daily_brief_recipient() -> None:
    account_id = uuid4()
    operations = Operations(account_id)
    service = AgentConsoleService(operations)  # type: ignore[arg-type]

    updated = await service.update_daily_brief_recipient(
        account_id=account_id,
        command=DailyBriefRecipientCommand(
            recipient="  new@example.test  ",
            expected_version=5,
        ),
    )

    assert updated.daily_brief_recipient == "new@example.test"
    assert operations.patches[0][0].daily_brief_recipient == "new@example.test"


@pytest.mark.asyncio
async def test_console_rejects_stale_manual_action_and_bounds_pending_batch() -> None:
    account_id = uuid4()
    operations = Operations(account_id)
    service = AgentConsoleService(operations)  # type: ignore[arg-type]

    with pytest.raises(OperationConflictError):
        await service.submit_operation(
            account_id=account_id,
            command=AgentOperationCommand(
                action=AgentManualAction.MAIL_SYNC,
                expected_control_version=4,
                idempotency_key="stale-operation-key",
            ),
        )
    with pytest.raises(ValueError, match="between 1 and 100"):
        await service.submit_operation(
            account_id=account_id,
            command=AgentOperationCommand(
                action=AgentManualAction.PROCESS_PENDING,
                expected_control_version=5,
                idempotency_key="bounded-operation-key",
                batch_limit=101,
            ),
        )
