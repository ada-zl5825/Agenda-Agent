"""PostgreSQL regression coverage for Phase 8 Brief queries and dispatch claims."""

import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from testcontainers.community.postgres import PostgresContainer

from recruitment_agent.persistence.daily_brief import SqlAlchemyDailyBriefStore
from recruitment_agent.persistence.models import DailyBriefModel, MicrosoftConnectionModel
from recruitment_agent.persistence.session import create_database_engine, create_session_factory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 on a Docker-enabled host",
    ),
]


@pytest.mark.asyncio
async def test_daily_brief_snapshot_and_claim_are_account_scoped_and_idempotent() -> None:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "head")
        engine = create_database_engine(database_url)
        session_factory = create_session_factory(engine)
        account_id = uuid4()
        async with session_factory.begin() as session:
            session.add(MicrosoftConnectionModel(id=account_id))

        store = SqlAlchemyDailyBriefStore(session_factory)
        brief_date = date(2026, 8, 13)
        snapshot = await store.load_snapshot(
            account_id=account_id,
            brief_date=brief_date,
            timezone="Europe/London",
            public_app_base_url="https://agent.example",
            generated_at=datetime(2026, 8, 13, 7, tzinfo=UTC),
        )
        first = await store.claim_dispatch(
            account_id=account_id,
            brief_date=brief_date,
            timezone="Europe/London",
        )
        repeated = await store.claim_dispatch(
            account_id=account_id,
            brief_date=brief_date,
            timezone="Europe/London",
        )
        await store.mark_accepted(account_id=account_id, brief_date=brief_date)
        async with session_factory() as session:
            audit = await session.scalar(select(DailyBriefModel))
        await engine.dispose()

    assert snapshot.items == ()
    assert first
    assert not repeated
    assert audit is not None
    assert audit.status == "accepted"
    assert audit.attempt_count == 1
    assert audit.error_code is None
