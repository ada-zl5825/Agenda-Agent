"""Production composition for Phase 8 Daily Brief preview and timer delivery."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.daily_brief import DailyBriefService
from recruitment_agent.briefs.renderer import DailyBriefRenderer, RenderedBrief
from recruitment_agent.config import (
    get_link_encryption_settings,
    get_microsoft_settings,
    get_settings,
)
from recruitment_agent.links.azure import azure_link_key_provider
from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService
from recruitment_agent.microsoft.crypto import AesGcmCipher
from recruitment_agent.microsoft.send_mail import GraphBriefMailClient
from recruitment_agent.persistence.daily_brief import SqlAlchemyDailyBriefStore
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore
from recruitment_agent.persistence.secure_links import SqlAlchemySecureLinkRepository
from recruitment_agent.persistence.session import create_database_engine, create_session_factory


async def run_daily_brief_job() -> bool | None:
    settings = get_microsoft_settings()
    if not settings.daily_brief_enabled:
        return None
    app_settings = get_settings()
    clock = SystemClock()
    if not is_daily_brief_delivery_hour(
        now=clock.now(),
        timezone=app_settings.user_timezone,
        local_hour=settings.daily_brief_local_hour,
    ):
        return None
    assert settings.daily_brief_recipient is not None
    async with _daily_brief_service() as service:
        return await service.send_today(
            account_id=settings.microsoft_connection_id,
            recipient=settings.daily_brief_recipient,
        )


def is_daily_brief_delivery_hour(
    *,
    now: datetime,
    timezone: str,
    local_hour: int,
) -> bool:
    """Filter the hourly UTC timer using the configured DST-aware local time."""
    return now.astimezone(ZoneInfo(timezone)).hour == local_hour


async def render_daily_brief_today(*, account_id: UUID) -> RenderedBrief:
    async with _daily_brief_service() as service:
        return await service.render_today(account_id=account_id)


@asynccontextmanager
async def _daily_brief_service() -> AsyncIterator[DailyBriefService]:
    app_settings = get_settings()
    microsoft = get_microsoft_settings()
    link_settings = get_link_encryption_settings()
    if microsoft.public_app_base_url is None:
        raise ValueError("PUBLIC_APP_BASE_URL is required for Daily Brief rendering")
    engine = create_database_engine(app_settings.database_url)
    session_factory = create_session_factory(engine)
    clock = SystemClock()
    auth = MicrosoftAuthorizationService(
        settings=microsoft,
        store=SqlAlchemyMicrosoftAuthStore(session_factory),
        cipher=AesGcmCipher(
            key=microsoft.token_cache_key_bytes,
            key_version=microsoft.token_cache_encryption_key_version,
        ),
        clock=clock,
    )
    try:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(microsoft.graph_request_timeout_seconds),
                follow_redirects=False,
            ) as http_client,
            azure_link_key_provider(link_settings) as key_provider,
        ):
            yield DailyBriefService(
                store=SqlAlchemyDailyBriefStore(session_factory),
                secure_links=SqlAlchemySecureLinkRepository(session_factory),
                link_encryptor=ActionLinkEncryptor(key_provider),
                mail_gateway=GraphBriefMailClient(
                    http_client=http_client,
                    token_provider=auth,
                    base_url=str(microsoft.graph_base_url),
                    max_attempts=microsoft.graph_max_retry_attempts,
                    max_retry_delay_seconds=microsoft.graph_max_retry_delay_seconds,
                ),
                renderer=DailyBriefRenderer(),
                clock=clock,
                timezone=app_settings.user_timezone,
                public_app_base_url=str(microsoft.public_app_base_url),
            )
    finally:
        await engine.dispose()
