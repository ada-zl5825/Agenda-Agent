"""Composition boundary for one scheduled Microsoft mail synchronization."""

import httpx

from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.mail_sync import MailSyncResult, MailSyncService
from recruitment_agent.config import get_microsoft_settings, get_settings
from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService
from recruitment_agent.microsoft.crypto import AesGcmCipher
from recruitment_agent.microsoft.graph import GraphMailClient
from recruitment_agent.persistence.mail import SqlAlchemyMailSyncStore
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore
from recruitment_agent.persistence.session import create_database_engine, create_session_factory


async def run_mail_sync_job(*, force: bool = False) -> MailSyncResult | None:
    """Build adapters, invoke the application service, and release network resources."""
    microsoft_settings = get_microsoft_settings()
    if not force and not microsoft_settings.mail_sync_enabled:
        return None

    database_settings = get_settings()
    engine = create_database_engine(database_settings.database_url)
    session_factory = create_session_factory(engine)
    clock = SystemClock()
    auth_service = MicrosoftAuthorizationService(
        settings=microsoft_settings,
        store=SqlAlchemyMicrosoftAuthStore(session_factory),
        cipher=AesGcmCipher(
            key=microsoft_settings.token_cache_key_bytes,
            key_version=microsoft_settings.token_cache_encryption_key_version,
        ),
        clock=clock,
    )
    timeout = httpx.Timeout(microsoft_settings.graph_request_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http_client:
            gateway = GraphMailClient(
                http_client=http_client,
                token_provider=auth_service,
                base_url=str(microsoft_settings.graph_base_url),
                max_attempts=microsoft_settings.graph_max_retry_attempts,
                max_retry_delay_seconds=microsoft_settings.graph_max_retry_delay_seconds,
            )
            service = MailSyncService(
                gateway=gateway,
                store=SqlAlchemyMailSyncStore(session_factory),
                clock=clock,
            )
            return await service.synchronize(
                account_id=microsoft_settings.microsoft_connection_id,
                folder_id=microsoft_settings.mail_folder_id,
            )
    finally:
        await engine.dispose()
