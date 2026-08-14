"""Account-scoped PostgreSQL read models for graphical Review pages."""

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.expression import Executable

from recruitment_agent.application.reviews import ReviewStore
from recruitment_agent.persistence.models import (
    ApplicationModel,
    CompanyModel,
    LlmExtractionModel,
    ProcessingRunModel,
    RecruitmentEventModel,
    ReviewItemModel,
    SecureLinkModel,
    SourceEmailModel,
)
from recruitment_agent.privacy.sanitizer import PrivacySanitizer
from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem

_OUTLOOK_HOSTS = frozenset(
    {"outlook.office.com", "outlook.office365.com", "outlook.live.com"}
)
_SUBJECT_SANITIZER = PrivacySanitizer()


class SqlAlchemyReviewStore(ReviewStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_open(self, *, account_id: UUID) -> tuple[ReviewQueueItem, ...]:
        statement = (
            select(
                ReviewItemModel,
                SourceEmailModel,
                ApplicationModel.role_name,
                ApplicationModel.raw_company_name,
                CompanyModel.display_name,
                LlmExtractionModel.extraction,
            )
            .join(ProcessingRunModel, ProcessingRunModel.id == ReviewItemModel.processing_run_id)
            .join(SourceEmailModel, SourceEmailModel.id == ProcessingRunModel.source_email_id)
            .outerjoin(ApplicationModel, ApplicationModel.id == SourceEmailModel.application_id)
            .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
            .outerjoin(
                LlmExtractionModel,
                LlmExtractionModel.processing_run_id == ProcessingRunModel.id,
            )
            .where(
                SourceEmailModel.account_id == account_id,
                ReviewItemModel.status == "open",
            )
            .order_by(ReviewItemModel.created_at)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
            orphan_rows = (await session.execute(self._orphan_statement(account_id))).all()
        items: list[ReviewQueueItem] = []
        for (
            review,
            source,
            role_name,
            raw_company_name,
            display_name,
            extraction,
        ) in rows:
            items.append(
                self._queue_item(
                    review_id=review.id,
                    source=source,
                    role_name=role_name,
                    raw_company_name=raw_company_name,
                    display_name=display_name,
                    extraction=extraction,
                    review_type=review.review_type,
                    reason=review.reason,
                    created_at=review.created_at,
                    orphaned=False,
                )
            )
        seen = {item.source_email_id for item in items}
        for (
            source,
            role_name,
            raw_company_name,
            display_name,
            extraction,
            run,
        ) in orphan_rows:
            if source.id in seen:
                continue
            items.append(
                self._queue_item(
                    review_id=run.id,
                    source=source,
                    role_name=role_name,
                    raw_company_name=raw_company_name,
                    display_name=display_name,
                    extraction=extraction,
                    review_type="ORPHANED_NEEDS_REVIEW",
                    reason="orphaned_needs_review",
                    created_at=run.started_at,
                    orphaned=True,
                )
            )
        return tuple(items)

    @staticmethod
    def _orphan_statement(account_id: UUID) -> Executable:
        open_review = exists(
            select(ReviewItemModel.id).where(
                ReviewItemModel.processing_run_id == ProcessingRunModel.id,
                ReviewItemModel.status == "open",
            )
        )
        return (
            select(
                SourceEmailModel,
                ApplicationModel.role_name,
                ApplicationModel.raw_company_name,
                CompanyModel.display_name,
                LlmExtractionModel.extraction,
                ProcessingRunModel,
            )
            .join(
                ProcessingRunModel,
                ProcessingRunModel.source_email_id == SourceEmailModel.id,
            )
            .outerjoin(ApplicationModel, ApplicationModel.id == SourceEmailModel.application_id)
            .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
            .outerjoin(
                LlmExtractionModel,
                LlmExtractionModel.processing_run_id == ProcessingRunModel.id,
            )
            .where(
                SourceEmailModel.account_id == account_id,
                SourceEmailModel.processing_status == "needs_review",
                ProcessingRunModel.status == "needs_review",
                ~open_review,
            )
            .order_by(ProcessingRunModel.started_at)
        )

    @staticmethod
    def _queue_item(
        *,
        review_id: UUID,
        source: SourceEmailModel,
        role_name: str | None,
        raw_company_name: str | None,
        display_name: str | None,
        extraction: object,
        review_type: str,
        reason: str,
        created_at: datetime,
        orphaned: bool,
    ) -> ReviewQueueItem:
        payload = extraction if isinstance(extraction, dict) else {}
        company_raw = payload.get("company_raw")
        role_raw = payload.get("role_raw")
        return ReviewQueueItem(
            id=review_id,
            source_email_id=source.id,
            review_type=review_type,
            reason=reason,
            created_at=created_at,
            company=display_name
            or raw_company_name
            or (company_raw if isinstance(company_raw, str) else None),
            role=role_name or (role_raw if isinstance(role_raw, str) else None),
            subject=_SUBJECT_SANITIZER.sanitize(source.subject).text,
            event_type=(
                payload.get("event_type") if isinstance(payload.get("event_type"), str) else None
            ),
            source_time_text=(
                payload.get("source_datetime_text")
                if isinstance(payload.get("source_datetime_text"), str)
                else payload.get("source_deadline_text")
                if isinstance(payload.get("source_deadline_text"), str)
                else None
            ),
            orphaned=orphaned,
        )

    async def get_detail(
        self,
        *,
        account_id: UUID,
        review_id: UUID,
    ) -> ReviewDetail | None:
        statement = (
            select(
                ReviewItemModel,
                ProcessingRunModel,
                SourceEmailModel,
                LlmExtractionModel,
                ApplicationModel,
                CompanyModel.display_name,
            )
            .join(ProcessingRunModel, ProcessingRunModel.id == ReviewItemModel.processing_run_id)
            .join(SourceEmailModel, SourceEmailModel.id == ProcessingRunModel.source_email_id)
            .outerjoin(
                LlmExtractionModel,
                LlmExtractionModel.processing_run_id == ProcessingRunModel.id,
            )
            .outerjoin(ApplicationModel, ApplicationModel.id == SourceEmailModel.application_id)
            .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
            .where(ReviewItemModel.id == review_id, SourceEmailModel.account_id == account_id)
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one_or_none()
            if row is None:
                return None
            review, run, source, extraction_model, application, company_name = row.tuple()
            current_event = None
            if application is not None:
                current_event = await session.scalar(
                    select(RecruitmentEventModel)
                    .where(RecruitmentEventModel.application_id == application.id)
                    .order_by(RecruitmentEventModel.updated_at.desc())
                    .limit(1)
                )
            link_models = (
                await session.scalars(
                    select(SecureLinkModel)
                    .where(SecureLinkModel.source_email_id == source.id)
                    .order_by(SecureLinkModel.ref)
                )
            ).all()
            candidates = await self._candidate_models(
                session,
                review_type=review.review_type,
                allowed_choices=tuple(review.allowed_choices),
            )

        extraction = {} if extraction_model is None else extraction_model.extraction
        validation = {} if extraction_model is None else extraction_model.validation
        raw_issues = validation.get("issues", []) if isinstance(validation, dict) else []
        issues = raw_issues if isinstance(raw_issues, list) else []
        findings = tuple(
            str(issue.get("code"))
            for issue in issues
            if isinstance(issue, dict) and issue.get("code") is not None
        )
        company_resolution = (
            None if extraction_model is None else extraction_model.company_resolution
        )
        role_resolution = None if extraction_model is None else extraction_model.role_resolution
        application_values = {
            "application_id": None if application is None else application.id,
            "canonical_company": company_name,
            "company_raw": extraction.get("company_raw"),
            "role_raw": extraction.get("role_raw"),
            "application_status": None if application is None else application.status,
        }
        extracted_values = {
            "event_type": extraction.get("event_type"),
            "interview_round": extraction.get("interview_round"),
            "action_summary": extraction.get("action_text"),
            "meeting_platform": extraction.get("meeting_platform"),
            "location": extraction.get("location"),
            "source_datetime_text": extraction.get("source_datetime_text"),
            "source_deadline_text": extraction.get("source_deadline_text"),
            "normalized_datetime": extraction.get("event_datetime"),
            "normalized_deadline": extraction.get("deadline"),
            "timezone_explicit": extraction.get("timezone_explicit"),
            "timezone_text": extraction.get("timezone_text"),
            "datetime_confidence": extraction.get("datetime_confidence"),
            "company_confidence": extraction.get("company_confidence"),
            "event_confidence": extraction.get("event_confidence"),
            "company_resolution": company_resolution,
            "role_resolution": role_resolution,
        }
        current_values = {
            "application_status": None if application is None else application.status,
            "event_id": None if current_event is None else current_event.id,
            "event_type": None if current_event is None else current_event.type,
            "round": None if current_event is None else current_event.round,
            "starts_at": None if current_event is None else current_event.starts_at,
            "deadline_at": None if current_event is None else current_event.deadline_at,
            "timezone": None if current_event is None else current_event.timezone,
        }
        proposed_values = {
            "record_kind": "new" if current_event is None else "update",
            "event_type": extraction.get("event_type"),
            "round": extraction.get("interview_round"),
            "starts_at": extraction.get("event_datetime"),
            "deadline_at": extraction.get("deadline"),
            "timezone": extraction.get("timezone_text"),
        }
        return ReviewDetail(
            id=review.id,
            account_id=source.account_id,
            processing_run_id=run.id,
            source_email_id=source.id,
            review_type=review.review_type,
            status=review.status,
            reason=review.reason,
            question=review.question,
            allowed_choices=tuple(review.allowed_choices),
            version=review.version,
            created_at=review.created_at,
            resolved_at=review.resolved_at,
            resolution=review.resolution,
            run_status=run.status,
            source={
                "subject": _SUBJECT_SANITIZER.sanitize(source.subject).text,
                "sender_domain": source.sender_domain,
                "received_at": source.received_at,
                "is_forwarded": None,
                "has_attachments": source.has_attachments,
                "open_original_email": self._safe_outlook_url(source.outlook_web_link),
            },
            application=application_values,
            extraction=extracted_values,
            validation_findings=findings,
            current_values=current_values,
            proposed_values=proposed_values,
            candidates=candidates,
            secure_links=tuple(
                {"ref": link.ref, "link_type": link.link_type, "domain": link.domain}
                for link in link_models
            ),
            side_effects=self._side_effects(review.review_type),
        )

    @staticmethod
    async def _candidate_models(
        session: AsyncSession,
        *,
        review_type: str,
        allowed_choices: tuple[str, ...],
    ) -> tuple[dict[str, object], ...]:
        ids: list[UUID] = []
        for choice in allowed_choices:
            try:
                ids.append(UUID(choice))
            except ValueError:
                continue
        if not ids:
            return ()
        candidates: list[dict[str, object]] = []
        if review_type == "UNCERTAIN_RESCHEDULE":
            event_rows = (
                await session.execute(
                    select(RecruitmentEventModel, ApplicationModel, CompanyModel.display_name)
                    .join(
                        ApplicationModel,
                        ApplicationModel.id == RecruitmentEventModel.application_id,
                    )
                    .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
                    .where(RecruitmentEventModel.id.in_(ids))
                )
            ).all()
            for event, application, company in event_rows:
                candidates.append(
                    {
                        "id": event.id,
                        "company": company or application.raw_company_name,
                        "role": application.role_name,
                        "status": event.status,
                        "event_type": event.type,
                        "round": event.round,
                        "time": event.starts_at or event.deadline_at,
                        "last_activity": event.updated_at,
                    }
                )
        else:
            application_rows = (
                await session.execute(
                    select(ApplicationModel, CompanyModel.display_name)
                    .outerjoin(CompanyModel, CompanyModel.id == ApplicationModel.company_id)
                    .where(ApplicationModel.id.in_(ids))
                )
            ).all()
            matched_ids: set[UUID] = set()
            for application, company in application_rows:
                matched_ids.add(application.id)
                candidates.append(
                    {
                        "id": application.id,
                        "company": company or application.raw_company_name,
                        "role": application.role_name,
                        "status": application.status,
                        "event_type": None,
                        "round": None,
                        "time": None,
                        "last_activity": application.updated_at,
                    }
                )
            remaining_ids = set(ids) - matched_ids
            if remaining_ids:
                company_rows = (
                    await session.scalars(
                        select(CompanyModel).where(CompanyModel.id.in_(remaining_ids))
                    )
                ).all()
                candidates.extend(
                    {
                        "id": company.id,
                        "company": company.display_name,
                        "role": None,
                        "status": company.status,
                        "event_type": None,
                        "round": None,
                        "time": None,
                        "last_activity": company.updated_at,
                    }
                    for company in company_rows
                )
        choice_order = {choice: index for index, choice in enumerate(allowed_choices)}
        candidates.sort(key=lambda candidate: choice_order.get(str(candidate["id"]), len(ids)))
        return tuple(candidates)

    @staticmethod
    def _side_effects(review_type: str) -> tuple[str, ...]:
        mapping = {
            "TIMEZONE_AMBIGUITY": (
                "Application/Event/ActionItem: blocked pending timezone decision",
                "Calendar: blocked",
            ),
            "APPLICATION_AMBIGUITY": (
                "Application resolution: blocked",
                "Event/ActionItem/Calendar: blocked",
            ),
            "DATETIME_CONFLICT": (
                "Event update: blocked pending explicit decision",
                "Calendar: blocked",
            ),
            "UNCERTAIN_RESCHEDULE": (
                "Existing Event selection/update: blocked",
                "Calendar update: blocked",
            ),
            "UNSAFE_CALENDAR_UPDATE": (
                "Domain values: already validated",
                "Calendar update/replacement: blocked",
            ),
        }
        return mapping.get(review_type, ("Workflow side effects: blocked",))

    @staticmethod
    def _safe_outlook_url(value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname not in _OUTLOOK_HOSTS:
            return None
        return value
