"""PostgreSQL regression coverage for Phase 7 Calendar links."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from testcontainers.community.postgres import PostgresContainer

from recruitment_agent.calendar.models import CalendarLinkSnapshot
from recruitment_agent.persistence.calendar import SqlAlchemyCalendarSyncStore
from recruitment_agent.persistence.models import (
    ApplicationModel,
    CalendarLinkModel,
    CompanyModel,
    MicrosoftConnectionModel,
    RecruitmentEventModel,
    SourceEmailModel,
)
from recruitment_agent.persistence.session import create_database_engine, create_session_factory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 on a Docker-enabled host",
    ),
]


@pytest.mark.asyncio
async def test_calendar_candidate_and_link_upsert_are_authoritative_and_idempotent() -> None:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "head")
        engine = create_database_engine(database_url)
        session_factory = create_session_factory(engine)
        account_id = uuid4()
        company_id = uuid4()
        application_id = uuid4()
        source_id = uuid4()
        event_id = uuid4()
        starts_at = datetime(2026, 8, 20, 13, tzinfo=UTC)
        async with session_factory.begin() as session:
            session.add(MicrosoftConnectionModel(id=account_id))
            session.add(
                CompanyModel(
                    id=company_id,
                    canonical_name="Nimbus Labs",
                    normalized_canonical_name="nimbus labs calendar test",
                    display_name="Nimbus Labs",
                    entity_type="employer",
                    status="active",
                )
            )
            session.add(
                ApplicationModel(
                    id=application_id,
                    company_id=company_id,
                    raw_company_name="Nimbus Labs",
                    role_name="Backend Engineer",
                    role_normalized="backend engineer",
                    status="interview_scheduled",
                )
            )
            session.add(
                SourceEmailModel(
                    id=source_id,
                    account_id=account_id,
                    graph_message_id="phase-7-calendar-message",
                    subject="Interview",
                    received_at=starts_at,
                    application_id=application_id,
                    outlook_web_link="https://outlook.office.com/mail/id/source",
                )
            )
            session.add(
                RecruitmentEventModel(
                    id=event_id,
                    application_id=application_id,
                    type="interview",
                    round="1",
                    starts_at=starts_at,
                    timezone="Europe/London",
                    source_datetime_text="20 August 2026 at 14:00 BST",
                    status="active",
                    semantic_fingerprint="phase-7-calendar-event",
                )
            )

        store = SqlAlchemyCalendarSyncStore(session_factory)
        candidate = await store.load_candidate(
            account_id=account_id,
            source_email_id=source_id,
            recruitment_event_id=event_id,
        )
        first = CalendarLinkSnapshot(
            recruitment_event_id=event_id,
            account_id=account_id,
            provider="microsoft_graph",
            calendar_event_id="immutable-event-1",
            content_fingerprint="a" * 64,
            last_synced_at=starts_at,
        )
        await store.save_link(first)
        await store.save_link(
            CalendarLinkSnapshot(
                recruitment_event_id=event_id,
                account_id=account_id,
                provider="microsoft_graph",
                calendar_event_id="immutable-event-1",
                content_fingerprint="b" * 64,
                last_synced_at=starts_at,
            )
        )
        async with session_factory() as session:
            link_count = await session.scalar(select(func.count()).select_from(CalendarLinkModel))
        link = await store.get_link(event_id)
        await engine.dispose()

    assert candidate.company_display_name == "Nimbus Labs"
    assert candidate.application_resolved
    assert link_count == 1
    assert link is not None
    assert link.content_fingerprint == "b" * 64
