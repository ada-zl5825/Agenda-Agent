from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from recruitment_agent.api.agent import get_agent_console_service
from recruitment_agent.api.app import create_app
from recruitment_agent.api.dependencies import get_web_session_manager
from recruitment_agent.application.agent_console import (
    AgentConsoleSnapshot,
    AgentControlCommand,
    AgentManualAction,
    AgentOperationCommand,
    DailyBriefRecipientCommand,
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
)
from recruitment_agent.domain.mail import MailSyncStatus
from recruitment_agent.web.security import WebSessionManager

NOW = datetime(2026, 8, 14, 8, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


def _snapshot(account_id: UUID) -> AgentConsoleSnapshot:
    control = RuntimeControl(
        account_id=account_id,
        mail_sync_enabled=True,
        workflow_enabled=True,
        calendar_write_enabled=True,
        daily_brief_enabled=True,
        daily_brief_recipient="brief@example.test",
        version=3,
        reason=ControlReason.MANUAL,
        updated_by="<script>alert(1)</script>",
        updated_at=NOW,
    )
    return AgentConsoleSnapshot(
        status=OperationsStatusSnapshot(
            control=control,
            capabilities=RuntimeCapabilities(
                workflow_processing_available=True,
                calendar_write_available=True,
                daily_brief_available=True,
            ),
            oauth_authorized=True,
            mail_sync=MailSyncStatusSnapshot(
                status=MailSyncStatus.IDLE,
                cursor_present=True,
                last_started_at=NOW,
                last_finished_at=NOW,
                error_code=None,
            ),
            source_email_counts={"pending": 2, "processed": 9},
            workflow_counts={"completed": 8, "needs_review": 1},
            open_review_count=1,
            operation_counts={"succeeded": 4},
            latest_brief_status="accepted",
            latest_brief_date="2026-08-14",
        ),
        readiness=ReadinessSnapshot(database_ready=True, oauth_authorized=True),
        selected_operation=None,
    )


class Console:
    def __init__(self, account_id: UUID) -> None:
        self.account_id = account_id
        self.snapshot = _snapshot(account_id)
        self.controls: list[AgentControlCommand] = []
        self.operations: list[AgentOperationCommand] = []
        self.recipients: list[DailyBriefRecipientCommand] = []

    async def get_snapshot(
        self,
        *,
        account_id: UUID,
        operation_id: UUID | None = None,
    ) -> AgentConsoleSnapshot:
        assert account_id == self.account_id
        if operation_id is None:
            return self.snapshot
        operation = OperationSnapshot(
            id=operation_id,
            account_id=account_id,
            operation_type=OperationType.MAIL_SYNC,
            status=OperationStatus.RUNNING,
            source_email_id=None,
            batch_limit=None,
            parent_operation_id=None,
            requested_at=NOW,
            started_at=NOW,
            finished_at=None,
            attempt_count=1,
            result=None,
            error_code=None,
        )
        return replace(self.snapshot, selected_operation=operation)

    async def update_control(
        self,
        *,
        account_id: UUID,
        command: AgentControlCommand,
    ) -> RuntimeControl:
        assert account_id == self.account_id
        self.controls.append(command)
        return self.snapshot.status.control

    async def submit_operation(
        self,
        *,
        account_id: UUID,
        command: AgentOperationCommand,
    ) -> OperationSnapshot:
        assert account_id == self.account_id
        self.operations.append(command)
        return OperationSnapshot(
            id=uuid4(),
            account_id=account_id,
            operation_type={
                AgentManualAction.MAIL_SYNC: OperationType.MAIL_SYNC,
                AgentManualAction.PROCESS_PENDING: OperationType.PROCESS_PENDING,
                AgentManualAction.SEND_DAILY_BRIEF: OperationType.SEND_DAILY_BRIEF,
            }[command.action],
            status=OperationStatus.QUEUED,
            source_email_id=None,
            batch_limit=command.batch_limit,
            parent_operation_id=None,
            requested_at=NOW,
            started_at=None,
            finished_at=None,
            attempt_count=0,
            result=None,
            error_code=None,
        )

    async def update_daily_brief_recipient(
        self,
        *,
        account_id: UUID,
        command: DailyBriefRecipientCommand,
    ) -> RuntimeControl:
        assert account_id == self.account_id
        self.recipients.append(command)
        return self.snapshot.status.control


@pytest.mark.asyncio
async def test_agent_console_requires_login_and_renders_privacy_safe_controls() -> None:
    account_id = uuid4()
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    console = Console(account_id)
    application = create_app()
    application.dependency_overrides[get_web_session_manager] = lambda: manager
    application.dependency_overrides[get_agent_console_service] = lambda: console
    transport = httpx.ASGITransport(app=application)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://agent.example",
        follow_redirects=False,
    ) as client:
        unauthenticated = await client.get("/agent")
        client.cookies.set(
            manager.cookie_name,
            manager.issue(
                account_id,
                admin_home_account_id="admin-account",
                admin_tenant_id=None,
            ),
        )
        page = await client.get("/agent")

    assert unauthenticated.status_code == 303
    assert unauthenticated.headers["location"] == "/auth/login?return_to=/agent"
    assert "brief@example.test" not in unauthenticated.text
    assert page.status_code == 200
    assert "Agent 控制台" in page.text
    assert "邮件同步" in page.text
    assert "招聘工作流" in page.text
    assert "Calendar 写入" in page.text
    assert "发送今日 Daily Brief" in page.text
    assert "Review 队列" in page.text
    assert "连接 / 更换 Outlook" in page.text
    assert "brief@example.test" in page.text
    assert "<script>" not in page.text
    assert "OPS_API_TOKEN" not in page.text


@pytest.mark.asyncio
async def test_agent_console_mutations_require_action_bound_csrf() -> None:
    account_id = uuid4()
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    console = Console(account_id)
    application = create_app()
    application.dependency_overrides[get_web_session_manager] = lambda: manager
    application.dependency_overrides[get_agent_console_service] = lambda: console
    transport = httpx.ASGITransport(app=application)
    session = manager.issue(
        account_id,
        admin_home_account_id="admin-account",
        admin_tenant_id=None,
    )

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://agent.example",
        follow_redirects=False,
    ) as client:
        client.cookies.set(manager.cookie_name, session)
        rejected = await client.post(
            "/agent/control/mail_sync",
            content="enabled=false&expected_version=3&csrf_token=wrong",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        control_csrf = manager.action_csrf_token(
            session_token=session,
            action="control:mail_sync",
            version=3,
        )
        accepted = await client.post(
            "/agent/control/mail_sync",
            content=(
                "enabled=false&expected_version=3&csrf_token=" + control_csrf
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        operation_csrf = manager.action_csrf_token(
            session_token=session,
            action="operation:send_daily_brief",
            version=3,
        )
        brief = await client.post(
            "/agent/operations/send_daily_brief",
            content=(
                "expected_version=3&idempotency_key=web-daily-brief-001&csrf_token="
                + operation_csrf
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        recipient_csrf = manager.action_csrf_token(
            session_token=session,
            action="settings:daily_brief_recipient",
            version=3,
        )
        recipient = await client.post(
            "/agent/settings/daily-brief-recipient",
            content=(
                "recipient=new%40example.test&expected_version=3&csrf_token="
                + recipient_csrf
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert rejected.status_code == 403
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/agent?notice=control-updated"
    assert console.controls[0].enabled is False
    assert brief.status_code == 303
    assert brief.headers["location"].startswith("/agent?operation_id=")
    assert console.operations[0].action is AgentManualAction.SEND_DAILY_BRIEF
    assert recipient.status_code == 303
    assert recipient.headers["location"] == "/agent?notice=recipient-updated"
    assert console.recipients[0].recipient == "new@example.test"
