"""Composition boundaries for the Phase 9A control plane and queue worker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.mail_sync import MailSyncResult
from recruitment_agent.application.operations import (
    OperationExecutor,
    OperationHandlers,
    OperationsControlService,
    RuntimeCapabilities,
    RuntimeControl,
    RuntimeControlDefaults,
    WorkflowOperationResult,
)
from recruitment_agent.config import (
    get_microsoft_settings,
    get_operations_settings,
    get_settings,
)
from recruitment_agent.config.settings import get_azure_openai_settings
from recruitment_agent.jobs.daily_brief import run_daily_brief_job, send_daily_brief_now
from recruitment_agent.jobs.mail_processing import (
    MailProcessingJobRequest,
    run_mail_processing_job,
)
from recruitment_agent.jobs.mail_sync import run_mail_sync_job
from recruitment_agent.operations.azure_queue import azure_operation_queue
from recruitment_agent.persistence.operations import SqlAlchemyOperationsStore
from recruitment_agent.persistence.session import create_database_engine, create_session_factory

LOGGER = logging.getLogger(__name__)
_RUNTIME_CONTROL_STARTUP_RETRY_DELAYS = (0.5, 1.0, 2.0)


@dataclass(frozen=True, slots=True)
class ProductionOperationHandlers(OperationHandlers):
    """Invoke existing application jobs; queue triggers contain no business logic."""

    async def synchronize_mail(self) -> MailSyncResult:
        result = await run_mail_sync_job(force=True)
        if result is None:
            raise RuntimeError("forced mail synchronization did not run")
        return result

    async def send_daily_brief(self, *, recipient: str) -> bool:
        return await send_daily_brief_now(recipient=recipient)

    async def process_email(
        self,
        *,
        source_email_id: UUID,
        processing_run_id: UUID,
        calendar_write_enabled: bool,
    ) -> WorkflowOperationResult:
        result = await run_mail_processing_job(
            MailProcessingJobRequest(
                source_email_id=source_email_id,
                processing_run_id=processing_run_id,
            ),
            calendar_write_enabled=calendar_write_enabled,
        )
        return WorkflowOperationResult(
            status=str(result.state["status"]),
            interrupted=result.interrupted,
        )


def runtime_control_defaults() -> RuntimeControlDefaults:
    settings = get_microsoft_settings()
    return RuntimeControlDefaults(
        mail_sync_enabled=settings.mail_sync_enabled,
        workflow_enabled=settings.workflow_processing_enabled,
        calendar_write_enabled=(
            settings.workflow_processing_enabled and settings.calendar_sync_enabled
        ),
        daily_brief_enabled=settings.daily_brief_enabled,
        daily_brief_recipient=settings.daily_brief_recipient,
    )


def runtime_capabilities() -> RuntimeCapabilities:
    settings = get_microsoft_settings()
    return RuntimeCapabilities(
        workflow_processing_available=get_azure_openai_settings().llm_enabled,
        calendar_write_available=settings.calendar_sync_enabled,
        daily_brief_available=(
            settings.public_app_base_url is not None
            and settings.web_session_signing_key is not None
        ),
    )


@asynccontextmanager
async def operations_control_service() -> AsyncIterator[OperationsControlService]:
    app_settings = get_settings()
    microsoft = get_microsoft_settings()
    operations = get_operations_settings()
    engine = create_database_engine(app_settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with azure_operation_queue(operations) as queue:
            yield OperationsControlService(
                store=SqlAlchemyOperationsStore(session_factory),
                queue=queue,
                clock=SystemClock(),
                account_id=microsoft.microsoft_connection_id,
                folder_id=microsoft.mail_folder_id,
                defaults=runtime_control_defaults(),
                capabilities=runtime_capabilities(),
            )
    finally:
        await engine.dispose()


async def run_operation_job(operation_id: UUID, *, delivery_attempt: int = 1) -> None:
    app_settings = get_settings()
    microsoft = get_microsoft_settings()
    operations = get_operations_settings()
    engine = create_database_engine(app_settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with azure_operation_queue(operations) as queue:
            executor = OperationExecutor(
                store=SqlAlchemyOperationsStore(session_factory),
                queue=queue,
                handlers=ProductionOperationHandlers(),
                clock=SystemClock(),
                account_id=microsoft.microsoft_connection_id,
                folder_id=microsoft.mail_folder_id,
                defaults=runtime_control_defaults(),
                capabilities=runtime_capabilities(),
            )
            await executor.execute(operation_id, delivery_attempt=delivery_attempt)
    finally:
        await engine.dispose()


async def run_operation_dispatch_job() -> int:
    """Recover queued database operations whose first queue send may have failed."""
    try:
        async with operations_control_service() as service:
            return await service.redispatch_queued()
    except Exception as exc:
        LOGGER.error(
            "operations_dispatch_unavailable:%s",
            type(exc).__name__,
            extra={"error_type": type(exc).__name__},
        )
        return 0


async def _read_scheduled_runtime_control() -> RuntimeControl:
    """Retry the complete cold-start composition before skipping a schedule."""
    for delay in (*_RUNTIME_CONTROL_STARTUP_RETRY_DELAYS, None):
        try:
            async with operations_control_service() as service:
                return await service.get_control()
        except Exception:
            if delay is None:
                raise
            await asyncio.sleep(delay)
    raise AssertionError("runtime control startup retry loop exhausted")


async def run_scheduled_mail_sync_job() -> None:
    try:
        if not (await _read_scheduled_runtime_control()).mail_sync_enabled:
            return
    except Exception as exc:
        LOGGER.error(
            "mail_sync_runtime_control_unavailable:%s",
            type(exc).__name__,
            extra={"error_type": type(exc).__name__},
        )
        return
    await run_mail_sync_job(force=True)


async def run_scheduled_daily_brief_job() -> None:
    try:
        if not runtime_capabilities().daily_brief_available:
            return
        control = await _read_scheduled_runtime_control()
        if not control.daily_brief_enabled or control.daily_brief_recipient is None:
            return
    except Exception as exc:
        LOGGER.error(
            "daily_brief_runtime_control_unavailable:%s",
            type(exc).__name__,
            extra={"error_type": type(exc).__name__},
        )
        return
    await run_daily_brief_job(
        recipient=control.daily_brief_recipient,
        force=True,
    )
