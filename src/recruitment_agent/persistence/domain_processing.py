"""Atomic PostgreSQL adapter for Phase 6 recruitment domain transitions."""

from collections.abc import Sequence
from uuid import UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.application.domain_processing import RecruitmentDomainStore
from recruitment_agent.domain.enums import ApplicationStatus, EventStatus, RecruitmentEventType
from recruitment_agent.domain.processing import (
    ApplicationSnapshot,
    DomainMutationResult,
    DomainTransitionPlan,
    EventMutationKind,
    EventSnapshot,
    next_application_status,
)
from recruitment_agent.persistence.models import (
    ActionItemModel,
    ApplicationModel,
    ApplicationStatusHistoryModel,
    EventHistoryModel,
    RecruitmentEventModel,
    SecureLinkModel,
    SourceEmailModel,
)

_APPLICATION_HISTORY_NAMESPACE = UUID("a2d50a89-84e9-4777-9cf9-7bf87d81a579")
_EVENT_HISTORY_NAMESPACE = UUID("6f6e111a-45a9-44df-9f03-f433a7ccb555")
_CLOSED_APPLICATION_STATUSES = {
    ApplicationStatus.REJECTED.value,
    ApplicationStatus.WITHDRAWN.value,
}


class SqlAlchemyRecruitmentDomainStore(RecruitmentDomainStore):
    """Revalidate and apply one plan under a single database transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def application_for_source_email(
        self,
        source_email_id: UUID,
    ) -> ApplicationSnapshot | None:
        statement = (
            select(ApplicationModel)
            .join(SourceEmailModel, SourceEmailModel.application_id == ApplicationModel.id)
            .where(SourceEmailModel.id == source_email_id)
        )
        async with self._session_factory() as session:
            model = await session.scalar(statement)
        return None if model is None else _application_snapshot(model)

    async def find_open_applications(
        self,
        *,
        company_id: UUID,
        role_normalized: str | None,
    ) -> Sequence[ApplicationSnapshot]:
        statement = select(ApplicationModel).where(
            ApplicationModel.company_id == company_id,
            ApplicationModel.status.not_in(_CLOSED_APPLICATION_STATUSES),
        )
        if role_normalized is not None:
            statement = statement.where(ApplicationModel.role_normalized == role_normalized)
        async with self._session_factory() as session:
            models = (await session.scalars(statement.order_by(ApplicationModel.id))).all()
        return tuple(_application_snapshot(model) for model in models)

    async def find_event_by_fingerprint(
        self,
        *,
        application_id: UUID,
        semantic_fingerprint: str,
    ) -> EventSnapshot | None:
        statement = select(RecruitmentEventModel).where(
            RecruitmentEventModel.application_id == application_id,
            RecruitmentEventModel.semantic_fingerprint == semantic_fingerprint,
        )
        async with self._session_factory() as session:
            model = await session.scalar(statement)
        return None if model is None else _event_snapshot(model)

    async def list_active_interviews(
        self,
        application_id: UUID,
    ) -> Sequence[EventSnapshot]:
        statement = (
            select(RecruitmentEventModel)
            .where(
                RecruitmentEventModel.application_id == application_id,
                RecruitmentEventModel.type == RecruitmentEventType.INTERVIEW.value,
                RecruitmentEventModel.status == EventStatus.ACTIVE.value,
            )
            .order_by(RecruitmentEventModel.starts_at.desc().nullslast(), RecruitmentEventModel.id)
        )
        async with self._session_factory() as session:
            models = (await session.scalars(statement)).all()
        return tuple(_event_snapshot(model) for model in models)

    async def apply_transition(
        self,
        plan: DomainTransitionPlan,
    ) -> DomainMutationResult:
        if not plan.mutations_allowed:
            return DomainMutationResult(
                application_id=None if plan.create_application else plan.application_id,
                event_id=None,
                action_item_ids=(),
                changed=False,
                no_mutation_reason=plan.no_mutation_reason,
            )

        async with self._session_factory.begin() as session:
            source = await session.scalar(
                select(SourceEmailModel)
                .where(SourceEmailModel.id == plan.source_email_id)
                .with_for_update()
            )
            if source is None:
                raise ValueError("source email does not exist")

            application, application_changed = await self._resolve_application_for_write(
                session,
                source=source,
                plan=plan,
            )
            status_changed = await self._apply_application_status(
                session,
                application=application,
                plan=plan,
            )
            event_id, event_changed = await self._apply_event(
                session,
                application_id=application.id,
                plan=plan,
            )
            action_ids, action_changed = await self._apply_action(
                session,
                application_id=application.id,
                plan=plan,
            )
            return DomainMutationResult(
                application_id=application.id,
                event_id=event_id,
                action_item_ids=action_ids,
                changed=(
                    application_changed
                    or status_changed
                    or event_changed
                    or action_changed
                ),
            )

    async def _resolve_application_for_write(
        self,
        session: AsyncSession,
        *,
        source: SourceEmailModel,
        plan: DomainTransitionPlan,
    ) -> tuple[ApplicationModel, bool]:
        if source.application_id is not None:
            linked_application = await session.get(ApplicationModel, source.application_id)
            if linked_application is None:
                raise RuntimeError("source email references a missing application")
            if linked_application.id != plan.application_id and (
                not plan.create_application
                or linked_application.company_id != plan.company_id
                or (
                    plan.role_normalized is not None
                    and linked_application.role_normalized != plan.role_normalized
                )
            ):
                raise RuntimeError("source-email application changed after resolution")
            return linked_application, False

        application: ApplicationModel | None = None
        if plan.create_application:
            lock_identity = (
                f"{plan.company_id}:{plan.role_normalized}"
                if plan.company_id is not None
                else f"source:{plan.source_email_id}"
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": lock_identity},
            )
            if (
                plan.company_id is not None
                and not plan.reviewed_create_new_application
            ):
                candidates = await self._find_open_for_write(
                    session,
                    company_id=plan.company_id,
                    role_normalized=plan.role_normalized,
                )
                if len(candidates) > 1:
                    raise RuntimeError("application identity became ambiguous during persistence")
                application = candidates[0] if candidates else None
            if application is None:
                application = ApplicationModel(
                    id=plan.application_id,
                    company_id=plan.company_id,
                    raw_company_name=plan.raw_company_name,
                    role_name=plan.role_name,
                    role_normalized=plan.role_normalized,
                    status=ApplicationStatus.UNKNOWN.value,
                    version=1,
                )
                session.add(application)
                await session.flush()
        else:
            application = await session.scalar(
                select(ApplicationModel)
                .where(ApplicationModel.id == plan.application_id)
                .with_for_update()
            )
        if application is None:
            raise ValueError("resolved application does not exist")
        source.application_id = application.id
        return application, True

    async def _find_open_for_write(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        role_normalized: str | None,
    ) -> list[ApplicationModel]:
        statement = select(ApplicationModel).where(
            ApplicationModel.company_id == company_id,
            ApplicationModel.status.not_in(_CLOSED_APPLICATION_STATUSES),
        )
        if role_normalized is not None:
            statement = statement.where(ApplicationModel.role_normalized == role_normalized)
        return list(
            (await session.scalars(statement.order_by(ApplicationModel.id).with_for_update())).all()
        )

    async def _apply_application_status(
        self,
        session: AsyncSession,
        *,
        application: ApplicationModel,
        plan: DomainTransitionPlan,
    ) -> bool:
        current = ApplicationStatus(application.status)
        target = next_application_status(current, plan.application_status_after)
        if target is current:
            return False
        history_id = uuid5(
            _APPLICATION_HISTORY_NAMESPACE,
            f"{plan.source_email_id}:{application.id}:{current.value}:{target.value}",
        )
        history_statement = insert(ApplicationStatusHistoryModel).values(
            id=history_id,
            application_id=application.id,
            from_status=current.value,
            to_status=target.value,
            reason="phase_6_deterministic_transition",
            source_email_id=plan.source_email_id,
        )
        await session.execute(history_statement.on_conflict_do_nothing(index_elements=["id"]))
        application.status = target.value
        application.version += 1
        return True

    async def _apply_event(
        self,
        session: AsyncSession,
        *,
        application_id: UUID,
        plan: DomainTransitionPlan,
    ) -> tuple[UUID | None, bool]:
        event = plan.event
        if event.kind is EventMutationKind.NONE:
            return event.event_id, False
        if event.event_id is None or event.type is None or event.semantic_fingerprint is None:
            raise ValueError("event mutation is incomplete")
        if event.kind is EventMutationKind.CREATE:
            statement = insert(RecruitmentEventModel).values(
                id=event.event_id,
                application_id=application_id,
                type=event.type.value,
                round=event.round,
                starts_at=event.starts_at,
                deadline_at=event.deadline_at,
                timezone=event.timezone,
                source_datetime_text=event.source_datetime_text,
                status=EventStatus.ACTIVE.value,
                semantic_fingerprint=event.semantic_fingerprint,
            )
            inserted = await session.scalar(
                statement.on_conflict_do_nothing(
                    index_elements=["application_id", "semantic_fingerprint"]
                ).returning(RecruitmentEventModel.id)
            )
            if inserted is not None:
                return inserted, True
            existing = await session.scalar(
                select(RecruitmentEventModel.id).where(
                    RecruitmentEventModel.application_id == application_id,
                    RecruitmentEventModel.semantic_fingerprint == event.semantic_fingerprint,
                )
            )
            if existing is None:
                raise RuntimeError("event upsert did not return an identity")
            return existing, False

        existing_event = await session.scalar(
            select(RecruitmentEventModel)
            .where(
                RecruitmentEventModel.id == event.event_id,
                RecruitmentEventModel.application_id == application_id,
                RecruitmentEventModel.type == RecruitmentEventType.INTERVIEW.value,
                RecruitmentEventModel.status == EventStatus.ACTIVE.value,
            )
            .with_for_update()
        )
        if existing_event is None:
            raise ValueError("reschedule target is no longer an active interview")
        changed = any(
            (
                existing_event.round != event.round,
                existing_event.starts_at != event.starts_at,
                existing_event.deadline_at != event.deadline_at,
                existing_event.timezone != event.timezone,
                existing_event.source_datetime_text != event.source_datetime_text,
                existing_event.semantic_fingerprint != event.semantic_fingerprint,
            )
        )
        if not changed:
            return existing_event.id, False
        history_id = uuid5(
            _EVENT_HISTORY_NAMESPACE,
            f"{plan.source_email_id}:{existing_event.id}:{event.semantic_fingerprint}",
        )
        history_statement = insert(EventHistoryModel).values(
            id=history_id,
            recruitment_event_id=existing_event.id,
            previous_starts_at=existing_event.starts_at,
            previous_deadline_at=existing_event.deadline_at,
            previous_timezone=existing_event.timezone,
            previous_status=existing_event.status,
            reason="interview_reschedule",
            source_email_id=plan.source_email_id,
        )
        await session.execute(history_statement.on_conflict_do_nothing(index_elements=["id"]))
        existing_event.round = event.round
        existing_event.starts_at = event.starts_at
        existing_event.deadline_at = event.deadline_at
        existing_event.timezone = event.timezone
        existing_event.source_datetime_text = event.source_datetime_text
        existing_event.semantic_fingerprint = event.semantic_fingerprint
        return existing_event.id, True

    async def _apply_action(
        self,
        session: AsyncSession,
        *,
        application_id: UUID,
        plan: DomainTransitionPlan,
    ) -> tuple[tuple[UUID, ...], bool]:
        action = plan.action_item
        if action is None:
            return (), False
        secure_link_id: UUID | None = None
        if action.secure_link_ref is not None:
            secure_link_id = await session.scalar(
                select(SecureLinkModel.id).where(
                    SecureLinkModel.source_email_id == plan.source_email_id,
                    SecureLinkModel.ref == action.secure_link_ref,
                )
            )
            if secure_link_id is None:
                raise ValueError("action link reference does not resolve to encrypted storage")
        statement = insert(ActionItemModel).values(
            id=action.id,
            application_id=application_id,
            source_email_id=plan.source_email_id,
            type=action.type.value,
            title=action.title,
            due_at=action.due_at,
            secure_link_id=secure_link_id,
            status="open",
            idempotency_key=action.idempotency_key,
        )
        inserted = await session.scalar(
            statement.on_conflict_do_nothing(
                index_elements=["application_id", "idempotency_key"]
            ).returning(ActionItemModel.id)
        )
        if inserted is not None:
            return (inserted,), True
        existing = await session.scalar(
            select(ActionItemModel.id).where(
                ActionItemModel.application_id == application_id,
                ActionItemModel.idempotency_key == action.idempotency_key,
            )
        )
        if existing is None:
            raise RuntimeError("action-item upsert did not return an identity")
        return (existing,), False


def _application_snapshot(model: ApplicationModel) -> ApplicationSnapshot:
    return ApplicationSnapshot(
        id=model.id,
        company_id=model.company_id,
        role_normalized=model.role_normalized,
        status=ApplicationStatus(model.status),
        version=model.version,
    )


def _event_snapshot(model: RecruitmentEventModel) -> EventSnapshot:
    return EventSnapshot(
        id=model.id,
        application_id=model.application_id,
        type=RecruitmentEventType(model.type),
        status=EventStatus(model.status),
        round=model.round,
        starts_at=model.starts_at,
        deadline_at=model.deadline_at,
        timezone=model.timezone,
        source_datetime_text=model.source_datetime_text,
        semantic_fingerprint=model.semantic_fingerprint,
    )
