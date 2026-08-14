"""PostgreSQL Daily Brief query and at-most-once dispatch audit."""

from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.application.daily_brief import (
    DISPATCH_ABANDONED_ERROR_CODE,
    BriefDispatchStatus,
    DailyBriefStore,
    resolve_dispatch_claim,
)
from recruitment_agent.briefs.models import BriefItem, BriefSection, DailyBriefSnapshot
from recruitment_agent.domain.enums import ActionStatus, ApplicationStatus, EventStatus
from recruitment_agent.persistence.models import (
    ActionItemModel,
    ApplicationModel,
    CompanyModel,
    DailyBriefModel,
    ProcessingRunModel,
    RecruitmentEventModel,
    ReviewItemModel,
    SecureLinkModel,
    SourceEmailModel,
)

_BRIEF_NAMESPACE = UUID("75ead7e4-d951-43c1-b327-cef60ed3ba89")
_OUTLOOK_HOSTS = frozenset(
    {"outlook.office.com", "outlook.office365.com", "outlook.live.com"}
)


def _require_utc(value: datetime) -> datetime:
    """Normalize database timestamps defensively; timestamptz should be aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SqlAlchemyDailyBriefStore(DailyBriefStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_snapshot(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        timezone: str,
        public_app_base_url: str,
        generated_at: datetime,
    ) -> DailyBriefSnapshot:
        zone = ZoneInfo(timezone)
        day_start = datetime.combine(brief_date, time.min, tzinfo=zone).astimezone(UTC)
        day_end = day_start + timedelta(days=1)
        next_48 = generated_at + timedelta(hours=48)
        items: list[BriefItem] = []
        async with self._session_factory() as session:
            event_rows = (
                await session.execute(
                    select(
                        RecruitmentEventModel,
                        ApplicationModel,
                        CompanyModel.display_name,
                        SourceEmailModel,
                    )
                    .join(
                        ApplicationModel,
                        ApplicationModel.id == RecruitmentEventModel.application_id,
                    )
                    .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
                    .join(
                        SourceEmailModel,
                        SourceEmailModel.application_id == ApplicationModel.id,
                    )
                    .where(
                        SourceEmailModel.account_id == account_id,
                        RecruitmentEventModel.status == EventStatus.ACTIVE.value,
                    )
                    .order_by(SourceEmailModel.received_at.desc())
                )
            ).all()
            action_rows = (
                await session.execute(
                    select(
                        ActionItemModel,
                        ApplicationModel,
                        CompanyModel.display_name,
                        SourceEmailModel,
                        SecureLinkModel,
                    )
                    .join(ApplicationModel, ApplicationModel.id == ActionItemModel.application_id)
                    .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
                    .join(SourceEmailModel, SourceEmailModel.id == ActionItemModel.source_email_id)
                    .outerjoin(
                        SecureLinkModel,
                        SecureLinkModel.id == ActionItemModel.secure_link_id,
                    )
                    .where(
                        SourceEmailModel.account_id == account_id,
                        ActionItemModel.status == ActionStatus.OPEN.value,
                    )
                    .order_by(ActionItemModel.due_at.asc().nullslast(), ActionItemModel.id)
                )
            ).all()
            review_rows = (
                await session.execute(
                    select(
                        ReviewItemModel,
                        SourceEmailModel,
                        ApplicationModel,
                        CompanyModel.display_name,
                    )
                    .join(
                        ProcessingRunModel,
                        ProcessingRunModel.id == ReviewItemModel.processing_run_id,
                    )
                    .join(
                        SourceEmailModel,
                        SourceEmailModel.id == ProcessingRunModel.source_email_id,
                    )
                    .outerjoin(
                        ApplicationModel,
                        ApplicationModel.id == SourceEmailModel.application_id,
                    )
                    .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
                    .where(
                        SourceEmailModel.account_id == account_id,
                        ReviewItemModel.status == "open",
                    )
                    .order_by(ReviewItemModel.created_at)
                )
            ).all()
            update_rows = (
                await session.execute(
                    select(SourceEmailModel, ApplicationModel, CompanyModel.display_name)
                    .join(ApplicationModel, ApplicationModel.id == SourceEmailModel.application_id)
                    .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
                    .where(
                        SourceEmailModel.account_id == account_id,
                        SourceEmailModel.received_at >= day_start,
                        SourceEmailModel.received_at < day_end,
                    )
                    .order_by(SourceEmailModel.received_at.desc())
                )
            ).all()
            waiting_rows = (
                await session.execute(
                    select(ApplicationModel, CompanyModel.display_name, SourceEmailModel)
                    .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
                    .join(
                        SourceEmailModel,
                        SourceEmailModel.application_id == ApplicationModel.id,
                    )
                    .where(
                        SourceEmailModel.account_id == account_id,
                        ApplicationModel.status.in_(
                            (
                                ApplicationStatus.APPLIED.value,
                                ApplicationStatus.ASSESSMENT_COMPLETED.value,
                                ApplicationStatus.INTERVIEW_COMPLETED.value,
                            )
                        ),
                    )
                    .order_by(SourceEmailModel.received_at.desc())
                )
            ).all()

        seen_events: set[UUID] = set()
        for event, application, company, source in event_rows:
            if event.id in seen_events:
                continue
            seen_events.add(event.id)
            moment = event.starts_at or event.deadline_at
            base = {
                "identity": f"event:{event.id}",
                "company": company or application.raw_company_name,
                "role": application.role_name,
                "stage": self._event_stage(event.type, event.round),
                "starts_at": event.starts_at,
                "deadline_at": event.deadline_at,
                "timezone": event.timezone,
                "original_email_url": self._safe_outlook_url(source.outlook_web_link),
            }
            sections: list[BriefSection] = []
            if moment is not None and day_start <= moment < day_end:
                sections.append(BriefSection.TODAY)
            if moment is not None and generated_at <= moment <= next_48:
                sections.append(BriefSection.NEXT_48_HOURS)
            if event.type in {"assessment", "deadline"}:
                sections.append(BriefSection.ASSESSMENTS)
            if event.type in {"interview", "interview_reschedule"}:
                sections.append(BriefSection.UPCOMING_INTERVIEWS)
            items.extend(BriefItem(section=section, **base) for section in sections)

        for action, application, company, source, secure_link in action_rows:
            items.append(
                BriefItem(
                    identity=f"action:{action.id}",
                    section=BriefSection.ACTION_REQUIRED,
                    company=company or application.raw_company_name,
                    role=application.role_name,
                    stage=action.title,
                    deadline_at=action.due_at,
                    detail=(
                        None
                        if secure_link is None
                        else f"Secure {secure_link.link_type} link · {secure_link.domain}"
                    ),
                    original_email_url=self._safe_outlook_url(source.outlook_web_link),
                    secure_link_id=action.secure_link_id,
                    action_label="Open action",
                )
            )

        for review, source, application, company in review_rows:
            items.append(
                BriefItem(
                    identity=f"review:{review.id}",
                    section=BriefSection.NEEDS_REVIEW,
                    company=(
                        None
                        if application is None
                        else company or application.raw_company_name
                    ),
                    role=None if application is None else application.role_name,
                    stage=review.review_type,
                    detail=review.reason,
                    review_id=review.id,
                    review_url=f"{public_app_base_url}/reviews/{review.id}",
                    original_email_url=self._safe_outlook_url(source.outlook_web_link),
                )
            )

        for source, application, company in update_rows:
            items.append(
                BriefItem(
                    identity=f"update:{source.id}",
                    section=BriefSection.NEW_UPDATES,
                    company=company or application.raw_company_name,
                    role=application.role_name,
                    stage="Recruitment update",
                    detail=application.status,
                    original_email_url=self._safe_outlook_url(source.outlook_web_link),
                )
            )

        seen_applications: set[UUID] = set()
        for application, company, source in waiting_rows:
            if application.id in seen_applications:
                continue
            seen_applications.add(application.id)
            items.append(
                BriefItem(
                    identity=f"waiting:{application.id}",
                    section=BriefSection.WAITING_FOR_RESULT,
                    company=company or application.raw_company_name,
                    role=application.role_name,
                    stage=application.status,
                    original_email_url=self._safe_outlook_url(source.outlook_web_link),
                )
            )
        return DailyBriefSnapshot(
            account_id=account_id,
            brief_date=brief_date,
            timezone=timezone,
            generated_at=generated_at,
            items=tuple(items),
        )

    async def claim_dispatch(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        timezone: str,
    ) -> bool:
        identity = uuid5(_BRIEF_NAMESPACE, f"{account_id}:{brief_date.isoformat()}")
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            inserted_id = await session.scalar(
                insert(DailyBriefModel)
                .values(
                    id=identity,
                    account_id=account_id,
                    brief_date=brief_date,
                    timezone=timezone,
                    status=BriefDispatchStatus.DISPATCHING.value,
                    attempt_count=1,
                    dispatch_started_at=now,
                )
                .on_conflict_do_nothing(index_elements=["account_id", "brief_date"])
                .returning(DailyBriefModel.id)
            )
            if inserted_id is not None:
                return True
            model = await session.scalar(
                select(DailyBriefModel)
                .where(
                    DailyBriefModel.account_id == account_id,
                    DailyBriefModel.brief_date == brief_date,
                )
                .with_for_update()
            )
            if model is None:
                raise RuntimeError("Daily Brief dispatch could not be claimed")
            decision = resolve_dispatch_claim(
                status=BriefDispatchStatus(model.status),
                attempt_count=model.attempt_count,
                dispatch_started_at=_require_utc(model.dispatch_started_at),
                now=now,
            )
            if decision.mark_abandoned:
                model.status = BriefDispatchStatus.UNCERTAIN.value
                model.error_code = DISPATCH_ABANDONED_ERROR_CODE
                return False
            if not decision.claim:
                return False
            model.status = BriefDispatchStatus.DISPATCHING.value
            model.attempt_count = model.attempt_count + 1
            model.dispatch_started_at = now
            model.error_code = None
            return True

    async def mark_accepted(self, *, account_id: UUID, brief_date: date) -> None:
        await self._set_status(
            account_id=account_id,
            brief_date=brief_date,
            status=BriefDispatchStatus.ACCEPTED,
            error_code=None,
        )

    async def mark_failed(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        status: BriefDispatchStatus,
        error_code: str,
    ) -> None:
        await self._set_status(
            account_id=account_id,
            brief_date=brief_date,
            status=status,
            error_code=error_code,
        )

    async def _set_status(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        status: BriefDispatchStatus,
        error_code: str | None,
    ) -> None:
        async with self._session_factory.begin() as session:
            model = await session.scalar(
                select(DailyBriefModel)
                .where(
                    DailyBriefModel.account_id == account_id,
                    DailyBriefModel.brief_date == brief_date,
                )
                .with_for_update()
            )
            if model is None or model.status != BriefDispatchStatus.DISPATCHING.value:
                raise RuntimeError("Daily Brief dispatch state is not active")
            model.status = status.value
            model.error_code = error_code
            if status is BriefDispatchStatus.ACCEPTED:
                model.accepted_at = datetime.now(UTC)

    @staticmethod
    def _event_stage(event_type: str, round_name: str | None) -> str:
        if event_type in {"interview", "interview_reschedule"}:
            return "Interview" if not round_name else f"Interview {round_name}"
        return "Assessment Deadline" if event_type in {"assessment", "deadline"} else event_type

    @staticmethod
    def _safe_outlook_url(value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname not in _OUTLOOK_HOSTS:
            return None
        return value
