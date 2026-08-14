"""Authenticated visual control-plane application service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from recruitment_agent.application.errors import (
    OperationConflictError,
    ReviewAccessDeniedError,
)
from recruitment_agent.application.operations import (
    ControlReason,
    OperationsControlService,
    OperationSnapshot,
    OperationsStatusSnapshot,
    OperationType,
    ReadinessSnapshot,
    RuntimeControl,
    RuntimeControlPatch,
)
from recruitment_agent.domain.recipient import normalize_recipient_address


class AgentControlSwitch(StrEnum):
    MAIL_SYNC = "mail_sync"
    WORKFLOW = "workflow"
    CALENDAR = "calendar"
    DAILY_BRIEF = "daily_brief"


class AgentManualAction(StrEnum):
    MAIL_SYNC = "mail_sync"
    PROCESS_PENDING = "process_pending"
    SEND_DAILY_BRIEF = "send_daily_brief"


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentConsoleSnapshot:
    status: OperationsStatusSnapshot
    readiness: ReadinessSnapshot
    selected_operation: OperationSnapshot | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentControlCommand:
    switch: AgentControlSwitch
    enabled: bool
    expected_version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentOperationCommand:
    action: AgentManualAction
    expected_control_version: int
    idempotency_key: str
    batch_limit: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyBriefRecipientCommand:
    recipient: str
    expected_version: int


class AgentConsoleService:
    """Account-scoped browser facade over the Phase 9A operations service."""

    def __init__(self, operations: OperationsControlService) -> None:
        self._operations = operations

    async def get_snapshot(
        self,
        *,
        account_id: UUID,
        operation_id: UUID | None = None,
    ) -> AgentConsoleSnapshot:
        status, readiness = await asyncio.gather(
            self._operations.get_status(),
            self._operations.get_readiness(),
        )
        self._require_account(account_id, status.control)
        operation = (
            None
            if operation_id is None
            else await self._operations.get_operation(operation_id)
        )
        return AgentConsoleSnapshot(
            status=status,
            readiness=readiness,
            selected_operation=operation,
        )

    async def update_control(
        self,
        *,
        account_id: UUID,
        command: AgentControlCommand,
    ) -> RuntimeControl:
        current = await self._operations.get_control()
        self._require_account(account_id, current)
        return await self._operations.update_control(
            RuntimeControlPatch(
                expected_version=command.expected_version,
                reason=ControlReason.MANUAL,
                mail_sync_enabled=(
                    command.enabled
                    if command.switch is AgentControlSwitch.MAIL_SYNC
                    else None
                ),
                workflow_enabled=(
                    command.enabled
                    if command.switch is AgentControlSwitch.WORKFLOW
                    else None
                ),
                calendar_write_enabled=(
                    command.enabled
                    if command.switch is AgentControlSwitch.CALENDAR
                    else None
                ),
                daily_brief_enabled=(
                    command.enabled
                    if command.switch is AgentControlSwitch.DAILY_BRIEF
                    else None
                ),
            ),
            updated_by="web_console",
        )

    async def submit_operation(
        self,
        *,
        account_id: UUID,
        command: AgentOperationCommand,
    ) -> OperationSnapshot:
        control = await self._operations.get_control()
        self._require_account(account_id, control)
        if control.version != command.expected_control_version:
            raise OperationConflictError("runtime control changed; refresh before submitting")
        operation_type = {
            AgentManualAction.MAIL_SYNC: OperationType.MAIL_SYNC,
            AgentManualAction.PROCESS_PENDING: OperationType.PROCESS_PENDING,
            AgentManualAction.SEND_DAILY_BRIEF: OperationType.SEND_DAILY_BRIEF,
        }[command.action]
        batch_limit = command.batch_limit
        if command.action is AgentManualAction.PROCESS_PENDING:
            if batch_limit is None or not 1 <= batch_limit <= 100:
                raise ValueError("process-pending limit must be between 1 and 100")
        elif batch_limit is not None:
            raise ValueError("this manual action does not accept a batch limit")
        return await self._operations.submit(
            operation_type=operation_type,
            idempotency_key=command.idempotency_key,
            batch_limit=batch_limit,
        )

    async def update_daily_brief_recipient(
        self,
        *,
        account_id: UUID,
        command: DailyBriefRecipientCommand,
    ) -> RuntimeControl:
        current = await self._operations.get_control()
        self._require_account(account_id, current)
        recipient = normalize_recipient_address(command.recipient)
        return await self._operations.update_control(
            RuntimeControlPatch(
                expected_version=command.expected_version,
                reason=ControlReason.MANUAL,
                daily_brief_recipient=recipient,
            ),
            updated_by="web_console",
        )

    @staticmethod
    def _require_account(account_id: UUID, control: RuntimeControl) -> None:
        if control.account_id != account_id:
            raise ReviewAccessDeniedError("browser session cannot access this control plane")
