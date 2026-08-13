"""PostgreSQL regression coverage for Phase 6 atomic mutations."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from testcontainers.community.postgres import PostgresContainer

from recruitment_agent.application.domain_processing import RecruitmentDomainService
from recruitment_agent.domain.enums import ApplicationStatus, RecruitmentEventType
from recruitment_agent.domain.processing import RecruitmentEvidence
from recruitment_agent.persistence.domain_processing import SqlAlchemyRecruitmentDomainStore
from recruitment_agent.persistence.models import (
    ActionItemModel,
    ApplicationModel,
    ApplicationStatusHistoryModel,
    CompanyModel,
    EventHistoryModel,
    MicrosoftConnectionModel,
    RecruitmentEventModel,
    SecureLinkModel,
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

COMPANY_ID = UUID("20000000-0000-0000-0000-000000000001")
ASSESSMENT_SOURCE_ID = UUID("20000000-0000-0000-0000-000000000002")
INTERVIEW_SOURCE_ID = UUID("20000000-0000-0000-0000-000000000003")
RESCHEDULE_SOURCE_ID = UUID("20000000-0000-0000-0000-000000000004")
RECEIVED_AT = datetime(2026, 8, 13, 8, tzinfo=UTC)


def _evidence(
    source_email_id: UUID,
    event_type: RecruitmentEventType,
    *,
    starts_at: datetime | None = None,
    deadline: datetime | None = None,
    action_required: bool = False,
) -> RecruitmentEvidence:
    return RecruitmentEvidence(
        source_email_id=source_email_id,
        company_id=COMPANY_ID,
        raw_company_name="Nimbus Labs",
        role_name="Graduate Engineer",
        role_normalized="graduate engineer",
        event_type=event_type,
        interview_round="first round"
        if event_type
        in {RecruitmentEventType.INTERVIEW, RecruitmentEventType.INTERVIEW_RESCHEDULE}
        else None,
        action_required=action_required,
        action_text="Complete the assessment" if action_required else None,
        action_link_ref="ACTION_LINK_01" if action_required else None,
        event_datetime=starts_at,
        deadline=deadline,
        timezone="Europe/London" if starts_at is not None or deadline is not None else None,
        source_datetime_text="reviewed explicit time" if starts_at is not None else None,
    )


@pytest.mark.asyncio
async def test_phase_six_retry_and_reschedule_are_atomic_and_idempotent() -> None:
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
            session.add(
                CompanyModel(
                    id=COMPANY_ID,
                    canonical_name="Nimbus Labs",
                    normalized_canonical_name="nimbus labs",
                    display_name="Nimbus Labs",
                    entity_type="employer",
                    parent_company_id=None,
                    status="active",
                )
            )
            for source_id, graph_id in (
                (ASSESSMENT_SOURCE_ID, "assessment-message"),
                (INTERVIEW_SOURCE_ID, "interview-message"),
                (RESCHEDULE_SOURCE_ID, "reschedule-message"),
            ):
                session.add(
                    SourceEmailModel(
                        id=source_id,
                        account_id=account_id,
                        graph_message_id=graph_id,
                        subject="Recruitment update",
                        received_at=RECEIVED_AT,
                        has_attachments=False,
                    )
                )
            session.add(
                SecureLinkModel(
                    id=uuid4(),
                    source_email_id=ASSESSMENT_SOURCE_ID,
                    ref="ACTION_LINK_01",
                    link_type="assessment",
                    domain="assessment.example.test",
                    encrypted_url=b"ciphertext-only",
                    nonce=b"nonce-value12",
                    encryption_key_version="v1",
                    display_text="assessment",
                )
            )

        service = RecruitmentDomainService(SqlAlchemyRecruitmentDomainStore(session_factory))
        assessment = _evidence(
            ASSESSMENT_SOURCE_ID,
            RecruitmentEventType.ASSESSMENT,
            deadline=datetime(2026, 8, 18, 16, tzinfo=UTC),
            action_required=True,
        )
        application = await service.resolve_application(assessment)
        event = await service.resolve_event(assessment, application)
        assessment_plan = service.plan_transition(assessment, application, event)
        results = [await service.persist(assessment_plan) for _ in range(5)]

        interview = _evidence(
            INTERVIEW_SOURCE_ID,
            RecruitmentEventType.INTERVIEW,
            starts_at=datetime(2026, 8, 20, 13, tzinfo=UTC),
        )
        application = await service.resolve_application(interview)
        event = await service.resolve_event(interview, application)
        interview_result = await service.persist(
            service.plan_transition(interview, application, event)
        )

        reschedule = _evidence(
            RESCHEDULE_SOURCE_ID,
            RecruitmentEventType.INTERVIEW_RESCHEDULE,
            starts_at=datetime(2026, 8, 22, 9, tzinfo=UTC),
        )
        application = await service.resolve_application(reschedule)
        event = await service.resolve_event(reschedule, application)
        reschedule_result = await service.persist(
            service.plan_transition(reschedule, application, event)
        )

        async with session_factory() as session:
            application_model = await session.scalar(select(ApplicationModel))
            application_count = await session.scalar(
                select(func.count()).select_from(ApplicationModel)
            )
            assessment_event_count = await session.scalar(
                select(func.count())
                .select_from(RecruitmentEventModel)
                .where(RecruitmentEventModel.type == RecruitmentEventType.ASSESSMENT.value)
            )
            interview_events = (
                await session.scalars(
                    select(RecruitmentEventModel).where(
                        RecruitmentEventModel.type == RecruitmentEventType.INTERVIEW.value
                    )
                )
            ).all()
            action_count = await session.scalar(
                select(func.count()).select_from(ActionItemModel)
            )
            status_history_count = await session.scalar(
                select(func.count()).select_from(ApplicationStatusHistoryModel)
            )
            event_history_count = await session.scalar(
                select(func.count()).select_from(EventHistoryModel)
            )
        await engine.dispose()

    assert results[0].changed
    assert all(not result.changed for result in results[1:])
    assert application_count == 1
    assert assessment_event_count == 1
    assert action_count == 1
    assert status_history_count == 2
    assert len(interview_events) == 1
    assert event_history_count == 1
    assert application_model is not None
    assert application_model.status == ApplicationStatus.INTERVIEW_SCHEDULED.value
    assert interview_result.event_id == reschedule_result.event_id
    assert interview_events[0].id == interview_result.event_id
    assert interview_events[0].starts_at == datetime(2026, 8, 22, 9, tzinfo=UTC)
