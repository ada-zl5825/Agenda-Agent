import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import func, select
from testcontainers.community.postgres import PostgresContainer

from recruitment_agent.application.secure_links import SecureActionLinkService
from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.links.key_provider import StaticLinkKeyProvider
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore
from recruitment_agent.persistence.models import SecureLinkModel, SourceEmailModel
from recruitment_agent.persistence.secure_links import SqlAlchemySecureLinkRepository
from recruitment_agent.persistence.session import create_database_engine, create_session_factory
from recruitment_agent.privacy.models import DiscoveredUrl, UrlSource

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 on a Docker-enabled host",
    ),
]


@pytest.mark.asyncio
async def test_secure_link_migration_and_idempotent_replace_against_postgres() -> None:
    plaintext_url = "https://assessment.example/start?token=phase-three-secret"
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "head")

        engine = create_database_engine(database_url)
        session_factory = create_session_factory(engine)
        account_id = uuid4()
        source_email_id = uuid4()
        now = datetime(2026, 8, 12, tzinfo=UTC)
        await SqlAlchemyMicrosoftAuthStore(session_factory).ensure_connection(account_id)
        async with session_factory.begin() as session:
            session.add(
                SourceEmailModel(
                    id=source_email_id,
                    account_id=account_id,
                    graph_message_id="secure-link-message",
                    subject="Assessment invitation",
                    sender_domain="example.com",
                    received_at=now,
                    has_attachments=False,
                )
            )

        repository = SqlAlchemySecureLinkRepository(session_factory)
        service = SecureActionLinkService(
            repository=repository,
            encryptor=ActionLinkEncryptor(
                StaticLinkKeyProvider(
                    current_version="test-v1",
                    keys={"test-v1": b"k" * 32},
                )
            ),
        )
        discovered = (
            DiscoveredUrl(
                ordinal=1,
                url=SecretStr(plaintext_url),
                domain="assessment.example",
                display_text="Start assessment",
                source=UrlSource.HTML_LINK,
            ),
        )

        first = await service.secure(
            source_email_id=source_email_id,
            discovered_urls=discovered,
            surrounding_text="Assessment invitation",
        )
        second = await service.secure(
            source_email_id=source_email_id,
            discovered_urls=discovered,
            surrounding_text="Assessment invitation",
        )
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(SecureLinkModel))
            stored = await session.scalar(select(SecureLinkModel))
        await engine.dispose()

    assert count == 1
    assert stored is not None
    assert first.links[0].id == second.links[0].id == stored.id
    assert plaintext_url.encode() not in stored.encrypted_url
    assert plaintext_url not in repr(first)
    assert stored.domain == "assessment.example"
    assert stored.encryption_key_version == "test-v1"
