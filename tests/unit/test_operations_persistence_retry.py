from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

import recruitment_agent.persistence.operations as operations_persistence
from recruitment_agent.application.operations import (
    ControlReason,
    RuntimeControl,
    RuntimeControlDefaults,
)
from recruitment_agent.persistence.operations import SqlAlchemyOperationsStore


@pytest.mark.asyncio
async def test_runtime_control_retries_transient_cold_start_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = uuid4()
    now = datetime(2026, 8, 14, 3, tzinfo=UTC)
    defaults = RuntimeControlDefaults(
        mail_sync_enabled=True,
        workflow_enabled=True,
        calendar_write_enabled=True,
        daily_brief_enabled=True,
        daily_brief_recipient="brief@example.test",
    )
    expected = RuntimeControl(
        account_id=account_id,
        mail_sync_enabled=True,
        workflow_enabled=True,
        calendar_write_enabled=True,
        daily_brief_enabled=True,
        daily_brief_recipient="brief@example.test",
        version=1,
        reason=ControlReason.MANUAL,
        updated_by="bootstrap",
        updated_at=now,
    )
    store = SqlAlchemyOperationsStore(object())  # type: ignore[arg-type]
    attempts = 0
    delays: list[float] = []

    async def flaky_control(**_kwargs: object) -> RuntimeControl:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("connect", {}, OSError("private network not ready"))
        return expected

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(store, "_ensure_control_once", flaky_control)
    monkeypatch.setattr(operations_persistence.asyncio, "sleep", record_sleep)

    result = await store.ensure_control(
        account_id=account_id,
        defaults=defaults,
        now=now,
    )

    assert result == expected
    assert attempts == 3
    assert delays == [0.5, 1.0]


@pytest.mark.asyncio
async def test_runtime_control_does_not_retry_non_connection_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyOperationsStore(object())  # type: ignore[arg-type]
    attempts = 0

    async def invalid_control(**_kwargs: object) -> RuntimeControl:
        nonlocal attempts
        attempts += 1
        raise ValueError("invalid control data")

    monkeypatch.setattr(store, "_ensure_control_once", invalid_control)

    with pytest.raises(ValueError, match="invalid control data"):
        await store.ensure_control(
            account_id=uuid4(),
            defaults=RuntimeControlDefaults(
                mail_sync_enabled=False,
                workflow_enabled=False,
                calendar_write_enabled=False,
                daily_brief_enabled=False,
                daily_brief_recipient=None,
            ),
            now=datetime(2026, 8, 14, 3, tzinfo=UTC),
        )

    assert attempts == 1
