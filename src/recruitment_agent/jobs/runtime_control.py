"""Shared runtime-control composition helpers for job entrypoints.

This module exists below both ``jobs.operations`` and ``jobs.mail_processing``
so the review-resume path can consult the same database-backed switches as the
operation executor without creating an import cycle.
"""

from __future__ import annotations

from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.operations import (
    RuntimeCapabilities,
    RuntimeControlDefaults,
)
from recruitment_agent.config import get_microsoft_settings, get_settings
from recruitment_agent.config.settings import get_azure_openai_settings
from recruitment_agent.persistence.operations import SqlAlchemyOperationsStore
from recruitment_agent.persistence.session import (
    create_database_engine,
    create_session_factory,
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


async def read_calendar_write_control() -> bool:
    """Combine the deployment capability with the database kill switch.

    Used by the review-resume path, which previously bypassed the runtime
    ``calendar_write_enabled`` switch entirely.
    """
    microsoft = get_microsoft_settings()
    if not microsoft.calendar_sync_enabled:
        return False
    engine = create_database_engine(get_settings().database_url)
    try:
        store = SqlAlchemyOperationsStore(create_session_factory(engine))
        control = await store.ensure_control(
            account_id=microsoft.microsoft_connection_id,
            defaults=runtime_control_defaults(),
            now=SystemClock().now(),
        )
        return control.calendar_write_enabled
    finally:
        await engine.dispose()
