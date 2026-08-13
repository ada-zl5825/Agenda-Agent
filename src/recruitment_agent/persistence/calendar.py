"""PostgreSQL adapter for Phase 7 Calendar read models and idempotency links."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.application.calendar_sync import CalendarSyncStore
from recruitment_agent.calendar.models import CalendarCandidate, CalendarLinkSnapshot
from recruitment_agent.domain.enums import EventStatus, RecruitmentEventType
from recruitment_agent.persistence.models import (
    ApplicationModel,
    CalendarLinkModel,
    CompanyModel,
    RecruitmentEventModel,
    SourceEmailModel,
)


class SqlAlchemyCalendarSyncStore(CalendarSyncStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_candidate(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        recruitment_event_id: UUID,
    ) -> CalendarCandidate:
        statement = (
            select(
                RecruitmentEventModel,
                ApplicationModel,
                CompanyModel.display_name,
                SourceEmailModel.outlook_web_link,
            )
            .join(
                ApplicationModel,
                ApplicationModel.id == RecruitmentEventModel.application_id,
            )
            .join(
                SourceEmailModel,
                SourceEmailModel.application_id == ApplicationModel.id,
            )
            .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
            .where(
                RecruitmentEventModel.id == recruitment_event_id,
                SourceEmailModel.id == source_email_id,
                SourceEmailModel.account_id == account_id,
            )
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one_or_none()
        if row is None:
            raise ValueError("calendar candidate does not match authoritative domain state")
        event, application, company_name, outlook_web_link = row.tuple()
        return CalendarCandidate(
            account_id=account_id,
            source_email_id=source_email_id,
            recruitment_event_id=event.id,
            application_id=application.id,
            application_resolved=application.company_id is not None and company_name is not None,
            company_display_name=company_name,
            role_name=application.role_name,
            event_type=RecruitmentEventType(event.type),
            event_status=EventStatus(event.status),
            interview_round=event.round,
            starts_at=event.starts_at,
            deadline_at=event.deadline_at,
            timezone=event.timezone,
            source_datetime_text=event.source_datetime_text,
            outlook_web_link=outlook_web_link,
        )

    async def get_link(
        self,
        recruitment_event_id: UUID,
    ) -> CalendarLinkSnapshot | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(CalendarLinkModel).where(
                    CalendarLinkModel.recruitment_event_id == recruitment_event_id
                )
            )
        return None if model is None else self._snapshot(model)

    async def save_link(self, link: CalendarLinkSnapshot) -> None:
        statement = insert(CalendarLinkModel).values(
            recruitment_event_id=link.recruitment_event_id,
            account_id=link.account_id,
            provider=link.provider,
            calendar_event_id=link.calendar_event_id,
            content_fingerprint=link.content_fingerprint,
            last_synced_at=link.last_synced_at,
        )
        excluded = statement.excluded
        async with self._session_factory.begin() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["recruitment_event_id"],
                    set_={
                        "account_id": excluded.account_id,
                        "provider": excluded.provider,
                        "calendar_event_id": excluded.calendar_event_id,
                        "content_fingerprint": excluded.content_fingerprint,
                        "last_synced_at": excluded.last_synced_at,
                        "updated_at": link.last_synced_at,
                    },
                )
            )

    @staticmethod
    def _snapshot(model: CalendarLinkModel) -> CalendarLinkSnapshot:
        return CalendarLinkSnapshot(
            recruitment_event_id=model.recruitment_event_id,
            account_id=model.account_id,
            provider=model.provider,
            calendar_event_id=model.calendar_event_id,
            content_fingerprint=model.content_fingerprint,
            last_synced_at=model.last_synced_at,
        )
