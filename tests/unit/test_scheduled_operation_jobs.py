from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

import recruitment_agent.jobs.operations as operation_jobs
from recruitment_agent.application.operations import ControlReason, RuntimeControl


def _control(*, mail_sync_enabled: bool = True) -> RuntimeControl:
    return RuntimeControl(
        account_id=uuid4(),
        mail_sync_enabled=mail_sync_enabled,
        workflow_enabled=True,
        calendar_write_enabled=True,
        daily_brief_enabled=True,
        daily_brief_recipient="brief@example.test",
        version=1,
        reason=ControlReason.MANUAL,
        updated_by="test",
        updated_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_scheduled_mail_sync_recovers_the_complete_cold_start_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    delays: list[float] = []
    syncs: list[bool] = []

    class Service:
        async def get_control(self) -> RuntimeControl:
            return _control()

    @asynccontextmanager
    async def flaky_service():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("private runtime is still starting")
        yield Service()

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async def record_sync(*, force: bool = False):
        syncs.append(force)

    monkeypatch.setattr(operation_jobs, "operations_control_service", flaky_service)
    monkeypatch.setattr(operation_jobs.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(operation_jobs, "run_mail_sync_job", record_sync)

    await operation_jobs.run_scheduled_mail_sync_job()

    assert attempts == 3
    assert delays == [0.5, 1.0]
    assert syncs == [True]


@pytest.mark.asyncio
async def test_exhausted_startup_retry_logs_only_the_exception_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    logged: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    @asynccontextmanager
    async def unavailable_service():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("sensitive detail must not be logged")
        yield  # pragma: no cover

    async def no_wait(_delay: float) -> None:
        pass

    def record_error(message: str, *args: object, **kwargs: object) -> None:
        logged.append((message, args, kwargs))

    monkeypatch.setattr(operation_jobs, "operations_control_service", unavailable_service)
    monkeypatch.setattr(operation_jobs.asyncio, "sleep", no_wait)
    monkeypatch.setattr(operation_jobs.LOGGER, "error", record_error)

    await operation_jobs.run_scheduled_mail_sync_job()

    assert attempts == 4
    assert logged[0][0] == "mail_sync_runtime_control_unavailable:%s"
    assert logged[0][1] == ("RuntimeError",)
    assert "sensitive detail" not in repr(logged)
