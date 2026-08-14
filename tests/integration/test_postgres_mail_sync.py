import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from testcontainers.community.postgres import PostgresContainer

from recruitment_agent.domain.mail import SourceEmailCandidate
from recruitment_agent.microsoft.crypto import EncryptedPayload
from recruitment_agent.persistence.mail import SqlAlchemyMailSyncStore
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore
from recruitment_agent.persistence.models import MailSyncStateModel, SourceEmailModel
from recruitment_agent.persistence.session import create_database_engine, create_session_factory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 on a Docker-enabled host",
    ),
]


@pytest.mark.asyncio
async def test_migrations_and_duplicate_mail_upsert_against_postgres() -> None:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "head")

        engine = create_database_engine(database_url)
        session_factory = create_session_factory(engine)
        account_id = uuid4()
        await SqlAlchemyMicrosoftAuthStore(session_factory).ensure_connection(account_id)
        store = SqlAlchemyMailSyncStore(session_factory)
        now = datetime(2026, 8, 12, tzinfo=UTC)
        message = SourceEmailCandidate(
            graph_message_id="graph-1",
            internet_message_id="<one@example.com>",
            subject="Interview",
            sender_domain="example.com",
            received_at=now,
            outlook_web_link=None,
            has_attachments=False,
        )

        await store.begin_sync(account_id=account_id, folder_id="inbox", started_at=now)
        first = await store.complete_sync(
            account_id=account_id,
            folder_id="inbox",
            messages=(message,),
            delta_link="https://graph.microsoft.com/v1.0/delta-1",
            finished_at=now,
        )
        await store.begin_sync(account_id=account_id, folder_id="inbox", started_at=now)
        second = await store.complete_sync(
            account_id=account_id,
            folder_id="inbox",
            messages=(message,),
            delta_link="https://graph.microsoft.com/v1.0/delta-2",
            finished_at=now,
        )
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(SourceEmailModel))
        await engine.dispose()

    assert (first.inserted, first.updated) == (1, 0)
    assert (second.inserted, second.updated) == (0, 1)
    assert count == 1


@pytest.mark.asyncio
async def test_explicit_mailbox_switch_clears_the_previous_delta_cursor() -> None:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "head")

        engine = create_database_engine(database_url)
        session_factory = create_session_factory(engine)
        account_id = uuid4()
        auth = SqlAlchemyMicrosoftAuthStore(session_factory)
        await auth.ensure_connection(account_id)
        payload = EncryptedPayload(ciphertext=b"cipher", nonce=b"n" * 12, key_version="v1")
        await auth.save_token_cache(
            connection_id=account_id,
            encrypted_cache=payload,
            expected_revision=0,
            home_account_id="old-account",
            tenant_id="tenant",
        )
        mail = SqlAlchemyMailSyncStore(session_factory)
        now = datetime(2026, 8, 12, tzinfo=UTC)
        await mail.begin_sync(account_id=account_id, folder_id="inbox", started_at=now)
        await mail.complete_sync(
            account_id=account_id,
            folder_id="inbox",
            messages=(),
            delta_link="https://graph.microsoft.com/v1.0/old-mailbox-delta",
            finished_at=now,
        )

        await auth.save_token_cache(
            connection_id=account_id,
            encrypted_cache=payload,
            expected_revision=1,
            home_account_id="new-account",
            tenant_id="tenant",
        )
        async with session_factory() as session:
            state = await session.scalar(
                select(MailSyncStateModel).where(
                    MailSyncStateModel.account_id == account_id,
                    MailSyncStateModel.folder_id == "inbox",
                )
            )
        await engine.dispose()

    assert state is not None
    assert state.delta_link is None
    assert state.last_sync_started_at is None
    assert state.last_sync_finished_at is None
