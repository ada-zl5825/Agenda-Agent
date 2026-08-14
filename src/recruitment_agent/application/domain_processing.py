"""Phase 6 application service for deterministic recruitment state changes."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from recruitment_agent.domain.enums import ApplicationStatus, RecruitmentEventType
from recruitment_agent.domain.processing import (
    ApplicationResolution,
    ApplicationResolutionKind,
    ApplicationSnapshot,
    DomainMutationResult,
    DomainTransitionPlan,
    EventMutationKind,
    EventResolution,
    EventResolutionKind,
    EventSnapshot,
    PlannedActionItem,
    PlannedEventMutation,
    RecruitmentEvidence,
    action_idempotency_key,
    action_type_for,
    desired_application_status,
    evidence_allows_mutation,
    new_action_item_id,
    new_application_id,
    new_event_id,
    next_application_status,
    semantic_fingerprint,
    tracked_event_type,
)


class RecruitmentDomainStore(Protocol):
    """Persistence boundary used by the provider-neutral Phase 6 service."""

    async def application_for_source_email(
        self,
        source_email_id: UUID,
    ) -> ApplicationSnapshot | None: ...

    async def find_open_applications(
        self,
        *,
        company_id: UUID,
        role_normalized: str | None,
    ) -> Sequence[ApplicationSnapshot]: ...

    async def find_event_by_fingerprint(
        self,
        *,
        application_id: UUID,
        semantic_fingerprint: str,
    ) -> EventSnapshot | None: ...

    async def list_active_interviews(
        self,
        application_id: UUID,
    ) -> Sequence[EventSnapshot]: ...

    async def apply_transition(
        self,
        plan: DomainTransitionPlan,
    ) -> DomainMutationResult: ...


class RecruitmentDomainService:
    """Resolve evidence, plan transitions, and persist through one atomic store call."""

    def __init__(self, store: RecruitmentDomainStore) -> None:
        self._store = store

    async def resolve_application(
        self,
        evidence: RecruitmentEvidence,
        *,
        selected_application_id: UUID | None = None,
        force_create: bool = False,
    ) -> ApplicationResolution:
        linked = await self._store.application_for_source_email(evidence.source_email_id)
        if linked is not None:
            if selected_application_id not in {None, linked.id}:
                raise ValueError("reviewed application conflicts with source-email identity")
            return _existing_application(linked, reason="source_email_link")

        if evidence.company_id is None:
            if not force_create:
                return ApplicationResolution(
                    kind=ApplicationResolutionKind.REVIEW,
                    application_id=None,
                    current_status=None,
                    reason="canonical_company_unresolved",
                )
            return _new_application(evidence, reason="reviewed_unresolved_company")

        candidates = tuple(
            sorted(
                await self._store.find_open_applications(
                    company_id=evidence.company_id,
                    role_normalized=evidence.role_normalized,
                ),
                key=lambda item: item.id,
            )
        )
        candidate_ids = tuple(candidate.id for candidate in candidates)
        if selected_application_id is not None:
            selected = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.id == selected_application_id
                ),
                None,
            )
            if selected is None:
                raise ValueError("reviewed application is not an allowed candidate")
            return _existing_application(selected, reason="reviewed_application")
        if force_create:
            return _new_application(evidence, reason="reviewed_create_new")
        if not candidates:
            return _new_application(evidence, reason="no_existing_application")
        if len(candidates) == 1:
            if evidence.role_name is not None and evidence.role_normalized is None:
                # The email names a role that could not be normalized, so the
                # single open application may belong to a different role at the
                # same company. Attaching automatically would corrupt history.
                return ApplicationResolution(
                    kind=ApplicationResolutionKind.REVIEW,
                    application_id=None,
                    current_status=None,
                    candidate_application_ids=candidate_ids,
                    reason="unnormalized_role_ambiguous",
                )
            return _existing_application(candidates[0], reason="exact_company_role")
        return ApplicationResolution(
            kind=ApplicationResolutionKind.REVIEW,
            application_id=None,
            current_status=None,
            candidate_application_ids=candidate_ids,
            reason="multiple_open_applications",
        )

    async def resolve_event(
        self,
        evidence: RecruitmentEvidence,
        application: ApplicationResolution,
        *,
        selected_event_id: UUID | None = None,
        treat_as_new: bool = False,
    ) -> EventResolution:
        if application.application_id is None:
            raise ValueError("event resolution requires a resolved application")
        fingerprint = semantic_fingerprint(evidence)
        tracked_type = tracked_event_type(evidence.event_type)
        if tracked_type is None:
            return EventResolution(
                kind=EventResolutionKind.NONE,
                event_id=None,
                semantic_fingerprint=None,
                reason="event_type_not_tracked",
            )

        if evidence.event_type is RecruitmentEventType.INTERVIEW_RESCHEDULE:
            candidates = tuple(
                sorted(
                    await self._store.list_active_interviews(application.application_id),
                    key=lambda item: item.id,
                )
            )
            round_matches = tuple(
                event
                for event in candidates
                if _same_round(event.round, evidence.interview_round)
            )
            if evidence.interview_round is not None and round_matches:
                candidates = round_matches
            candidate_ids = tuple(candidate.id for candidate in candidates)
            if selected_event_id is not None:
                selected = next(
                    (item for item in candidates if item.id == selected_event_id),
                    None,
                )
                if selected is None:
                    raise ValueError("reviewed event is not an allowed candidate")
                return EventResolution(
                    kind=EventResolutionKind.RESCHEDULE,
                    event_id=selected.id,
                    semantic_fingerprint=fingerprint,
                    reason="reviewed_reschedule_target",
                )
            if treat_as_new:
                return EventResolution(
                    kind=EventResolutionKind.CREATE,
                    event_id=new_event_id(evidence.source_email_id, fingerprint),
                    semantic_fingerprint=fingerprint,
                    reason="reviewed_new_interview",
                )
            if len(candidates) == 1:
                return EventResolution(
                    kind=EventResolutionKind.RESCHEDULE,
                    event_id=candidates[0].id,
                    semantic_fingerprint=fingerprint,
                    reason="single_active_interview",
                )
            return EventResolution(
                kind=EventResolutionKind.REVIEW,
                event_id=None,
                semantic_fingerprint=fingerprint,
                candidate_event_ids=candidate_ids,
                reason="reschedule_target_uncertain",
            )

        dated = evidence.event_datetime is not None or evidence.deadline is not None
        if dated:
            duplicate = await self._store.find_event_by_fingerprint(
                application_id=application.application_id,
                semantic_fingerprint=fingerprint,
            )
            if duplicate is not None:
                return EventResolution(
                    kind=EventResolutionKind.DUPLICATE,
                    event_id=duplicate.id,
                    semantic_fingerprint=fingerprint,
                    reason="semantic_duplicate",
                )

        if tracked_type is RecruitmentEventType.INTERVIEW and not treat_as_new:
            changed = await self._same_round_time_change(
                application.application_id,
                evidence,
            )
            if changed is not None:
                return changed

        return EventResolution(
            kind=EventResolutionKind.CREATE,
            event_id=new_event_id(evidence.source_email_id, fingerprint),
            semantic_fingerprint=fingerprint,
            reason="new_event",
        )

    async def _same_round_time_change(
        self,
        application_id: UUID,
        evidence: RecruitmentEvidence,
    ) -> EventResolution | None:
        """Update the only same-round interview when a later email changes its time.

        Recruiters often send a new invitation instead of an explicit reschedule.
        Creating a second event would duplicate the Outlook calendar item. Two
        undated interviews must not collapse: their fingerprints are identical
        once datetime and deadline are both null.
        """
        if evidence.event_datetime is None:
            return None
        candidates = tuple(
            event
            for event in await self._store.list_active_interviews(application_id)
            if _same_round(event.round, evidence.interview_round)
        )
        if len(candidates) != 1:
            return None
        existing = candidates[0]
        if existing.starts_at is not None and _same_instant(
            existing.starts_at,
            evidence.event_datetime,
        ):
            return None
        return EventResolution(
            kind=EventResolutionKind.RESCHEDULE,
            event_id=existing.id,
            semantic_fingerprint=semantic_fingerprint(evidence),
            reason="interview_time_changed",
        )

    def plan_transition(
        self,
        evidence: RecruitmentEvidence,
        application: ApplicationResolution,
        event: EventResolution,
    ) -> DomainTransitionPlan:
        if application.application_id is None or application.current_status is None:
            raise ValueError("transition planning requires a resolved application")
        if event.kind is EventResolutionKind.REVIEW:
            raise ValueError("transition planning cannot bypass event review")

        allowed, no_mutation_reason = evidence_allows_mutation(evidence)
        current_status = application.current_status
        desired = desired_application_status(evidence)
        target_status = next_application_status(current_status, desired)
        if not allowed:
            target_status = current_status

        event_mutation = _planned_event(evidence, event, allowed=allowed)
        action_item = _planned_action(evidence, event) if allowed else None
        return DomainTransitionPlan(
            source_email_id=evidence.source_email_id,
            application_id=application.application_id,
            create_application=application.kind is ApplicationResolutionKind.CREATE,
            reviewed_create_new_application=application.reason == "reviewed_create_new",
            company_id=evidence.company_id,
            raw_company_name=evidence.raw_company_name,
            role_name=evidence.role_name,
            role_normalized=evidence.role_normalized,
            application_status_before=current_status,
            application_status_after=target_status,
            event=event_mutation,
            action_item=action_item,
            mutations_allowed=allowed,
            no_mutation_reason=no_mutation_reason,
        )

    async def persist(self, plan: DomainTransitionPlan) -> DomainMutationResult:
        return await self._store.apply_transition(plan)


def _existing_application(
    application: ApplicationSnapshot,
    *,
    reason: str,
) -> ApplicationResolution:
    return ApplicationResolution(
        kind=ApplicationResolutionKind.EXISTING,
        application_id=application.id,
        current_status=application.status,
        reason=reason,
    )


def _new_application(
    evidence: RecruitmentEvidence,
    *,
    reason: str,
) -> ApplicationResolution:
    return ApplicationResolution(
        kind=ApplicationResolutionKind.CREATE,
        application_id=new_application_id(evidence.source_email_id),
        current_status=ApplicationStatus.UNKNOWN,
        reason=reason,
    )


def _same_round(existing: str | None, proposed: str | None) -> bool:
    if existing is None or proposed is None:
        return existing is proposed
    return " ".join(existing.casefold().split()) == " ".join(proposed.casefold().split())


def _same_instant(left: datetime, right: datetime) -> bool:
    return left.astimezone(UTC) == right.astimezone(UTC)


def _planned_event(
    evidence: RecruitmentEvidence,
    resolution: EventResolution,
    *,
    allowed: bool,
) -> PlannedEventMutation:
    mutation_kind = EventMutationKind.NONE
    if allowed and resolution.kind is EventResolutionKind.CREATE:
        mutation_kind = EventMutationKind.CREATE
    elif allowed and resolution.kind is EventResolutionKind.RESCHEDULE:
        mutation_kind = EventMutationKind.UPDATE
    return PlannedEventMutation(
        kind=mutation_kind,
        event_id=resolution.event_id,
        type=tracked_event_type(evidence.event_type),
        round=evidence.interview_round,
        starts_at=evidence.event_datetime,
        deadline_at=evidence.deadline,
        timezone=evidence.timezone,
        source_datetime_text=(evidence.source_datetime_text or evidence.source_deadline_text),
        semantic_fingerprint=resolution.semantic_fingerprint,
    )


def _planned_action(
    evidence: RecruitmentEvidence,
    resolution: EventResolution,
) -> PlannedActionItem | None:
    if not evidence.action_required:
        return None
    action_type = action_type_for(evidence)
    title = " ".join((evidence.action_text or "Recruitment action required").split())[:255]
    fingerprint = resolution.semantic_fingerprint or semantic_fingerprint(evidence)
    idempotency_key = action_idempotency_key(
        evidence,
        event_fingerprint=fingerprint,
        action_type=action_type,
        title=title,
    )
    return PlannedActionItem(
        id=new_action_item_id(evidence.source_email_id, idempotency_key),
        type=action_type,
        title=title,
        due_at=evidence.deadline,
        secure_link_ref=evidence.action_link_ref,
        idempotency_key=idempotency_key,
    )
