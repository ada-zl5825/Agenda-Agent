"""Deterministic Phase 6 application, event, and transition contracts."""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from recruitment_agent.domain.enums import (
    ActionType,
    ApplicationStatus,
    EventStatus,
    RecruitmentEventType,
)
from recruitment_agent.domain.role import normalize_role_name
from recruitment_agent.domain.time import require_optional_aware


class ApplicationResolutionKind(StrEnum):
    EXISTING = "existing"
    CREATE = "create"
    REVIEW = "review"


class EventResolutionKind(StrEnum):
    NONE = "none"
    CREATE = "create"
    DUPLICATE = "duplicate"
    RESCHEDULE = "reschedule"
    REVIEW = "review"


class EventMutationKind(StrEnum):
    NONE = "none"
    CREATE = "create"
    UPDATE = "update"


class ApplicationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    company_id: UUID | None
    role_normalized: str | None
    status: ApplicationStatus
    version: int = Field(ge=1)


class EventSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    application_id: UUID
    type: RecruitmentEventType
    status: EventStatus
    round: str | None
    starts_at: datetime | None
    deadline_at: datetime | None
    timezone: str | None
    source_datetime_text: str | None
    semantic_fingerprint: str | None

    @field_validator("starts_at", "deadline_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        require_optional_aware(value, field_name="event datetime")
        return value


class RecruitmentEvidence(BaseModel):
    """Validated semantic evidence; never an instruction to mutate storage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_email_id: UUID
    company_id: UUID | None
    raw_company_name: str | None = Field(repr=False)
    role_name: str | None = Field(repr=False)
    role_normalized: str | None = Field(repr=False)
    event_type: RecruitmentEventType
    interview_round: str | None = Field(repr=False)
    action_required: bool
    action_text: str | None = Field(repr=False)
    action_link_ref: str | None
    event_datetime: datetime | None
    deadline: datetime | None
    timezone: str | None = Field(repr=False)
    source_datetime_text: str | None = Field(repr=False)
    source_deadline_text: str | None = Field(default=None, repr=False)

    @field_validator("event_datetime", "deadline")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        require_optional_aware(value, field_name="evidence datetime")
        return value

    @model_validator(mode="after")
    def validate_normalized_role(self) -> "RecruitmentEvidence":
        if self.role_name is None:
            if self.role_normalized is not None:
                raise ValueError("missing role cannot have a normalized value")
        elif self.role_normalized != normalize_role_name(self.role_name):
            raise ValueError("role_normalized must use deterministic normalization")
        return self


class ApplicationResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ApplicationResolutionKind
    application_id: UUID | None
    current_status: ApplicationStatus | None
    candidate_application_ids: tuple[UUID, ...] = ()
    reason: str

    @model_validator(mode="after")
    def validate_shape(self) -> "ApplicationResolution":
        if self.kind is ApplicationResolutionKind.REVIEW:
            if self.application_id is not None:
                raise ValueError("review resolution cannot select an application")
        elif self.application_id is None or self.current_status is None:
            raise ValueError("resolved application must include identity and status")
        if len(self.candidate_application_ids) != len(set(self.candidate_application_ids)):
            raise ValueError("candidate application IDs must be unique")
        return self


class EventResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EventResolutionKind
    event_id: UUID | None
    semantic_fingerprint: str | None
    candidate_event_ids: tuple[UUID, ...] = ()
    reason: str

    @model_validator(mode="after")
    def validate_shape(self) -> "EventResolution":
        event_required = {
            EventResolutionKind.CREATE,
            EventResolutionKind.DUPLICATE,
            EventResolutionKind.RESCHEDULE,
        }
        if self.kind in event_required and self.event_id is None:
            raise ValueError("event resolution requires an event identity")
        if self.kind is EventResolutionKind.REVIEW and self.event_id is not None:
            raise ValueError("review resolution cannot select an event")
        if len(self.candidate_event_ids) != len(set(self.candidate_event_ids)):
            raise ValueError("candidate event IDs must be unique")
        return self


class PlannedEventMutation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EventMutationKind
    event_id: UUID | None
    type: RecruitmentEventType | None
    round: str | None = Field(repr=False)
    starts_at: datetime | None
    deadline_at: datetime | None
    timezone: str | None = Field(repr=False)
    source_datetime_text: str | None = Field(repr=False)
    semantic_fingerprint: str | None

    @field_validator("starts_at", "deadline_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        require_optional_aware(value, field_name="planned event datetime")
        return value


class PlannedActionItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    type: ActionType
    title: str = Field(min_length=1, max_length=255, repr=False)
    due_at: datetime | None
    secure_link_ref: str | None
    idempotency_key: str = Field(min_length=64, max_length=64)

    @field_validator("due_at")
    @classmethod
    def require_aware_due_at(cls, value: datetime | None) -> datetime | None:
        require_optional_aware(value, field_name="action due_at")
        return value


class DomainTransitionPlan(BaseModel):
    """Checkpoint-safe intent. The store revalidates it in one transaction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_email_id: UUID
    application_id: UUID
    create_application: bool
    reviewed_create_new_application: bool = False
    company_id: UUID | None
    raw_company_name: str | None = Field(repr=False)
    role_name: str | None = Field(repr=False)
    role_normalized: str | None = Field(repr=False)
    application_status_before: ApplicationStatus
    application_status_after: ApplicationStatus
    event: PlannedEventMutation
    action_item: PlannedActionItem | None = Field(repr=False)
    mutations_allowed: bool = True
    no_mutation_reason: str | None = None

    @model_validator(mode="after")
    def validate_mutation_guard(self) -> "DomainTransitionPlan":
        if self.mutations_allowed == (self.no_mutation_reason is not None):
            raise ValueError("mutation guard and reason are inconsistent")
        return self


class DomainMutationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    application_id: UUID | None
    event_id: UUID | None
    action_item_ids: tuple[UUID, ...]
    changed: bool
    no_mutation_reason: str | None = None


_APPLICATION_NAMESPACE = UUID("b74947d2-4a71-40a5-902b-2fc0876347cc")
_EVENT_NAMESPACE = UUID("53cd7758-ae1c-43e8-a9af-a4b17a4a381f")
_ACTION_NAMESPACE = UUID("9d4fd2b9-ea31-4877-ad7f-c97fc12fa59c")


def new_application_id(source_email_id: UUID) -> UUID:
    return uuid5(_APPLICATION_NAMESPACE, str(source_email_id))


def new_event_id(source_email_id: UUID, semantic_fingerprint: str) -> UUID:
    return uuid5(_EVENT_NAMESPACE, f"{source_email_id}:{semantic_fingerprint}")


def new_action_item_id(source_email_id: UUID, idempotency_key: str) -> UUID:
    return uuid5(_ACTION_NAMESPACE, f"{source_email_id}:{idempotency_key}")


def semantic_fingerprint(evidence: RecruitmentEvidence) -> str:
    """Hash normalized semantic identity, never raw email content or secret URLs."""
    event_type = (
        RecruitmentEventType.INTERVIEW
        if evidence.event_type is RecruitmentEventType.INTERVIEW_RESCHEDULE
        else evidence.event_type
    )
    payload = json.dumps(
        {
            "company_id": None if evidence.company_id is None else str(evidence.company_id),
            "role": evidence.role_normalized,
            "event_type": event_type.value,
            "round": _normalized_optional(evidence.interview_round),
            "event_datetime": _normalized_datetime(evidence.event_datetime),
            "deadline": _normalized_datetime(evidence.deadline),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def action_idempotency_key(
    evidence: RecruitmentEvidence,
    *,
    event_fingerprint: str,
    action_type: ActionType,
    title: str,
) -> str:
    payload = json.dumps(
        {
            "event": event_fingerprint,
            "action_type": action_type.value,
            "title": " ".join(title.casefold().split()),
            "due_at": _normalized_datetime(evidence.deadline),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def desired_application_status(evidence: RecruitmentEvidence) -> ApplicationStatus:
    mapping = {
        RecruitmentEventType.APPLICATION_RECEIVED: ApplicationStatus.APPLIED,
        RecruitmentEventType.ASSESSMENT: ApplicationStatus.ASSESSMENT_PENDING,
        RecruitmentEventType.INTERVIEW: (
            ApplicationStatus.INTERVIEW_SCHEDULED
            if evidence.event_datetime is not None
            else ApplicationStatus.INTERVIEW_PENDING
        ),
        RecruitmentEventType.INTERVIEW_RESCHEDULE: ApplicationStatus.INTERVIEW_SCHEDULED,
        RecruitmentEventType.OFFER: ApplicationStatus.OFFER,
        RecruitmentEventType.REJECTION: ApplicationStatus.REJECTED,
    }
    return mapping.get(evidence.event_type, ApplicationStatus.UNKNOWN)


def next_application_status(
    current: ApplicationStatus,
    desired: ApplicationStatus,
) -> ApplicationStatus:
    """Apply monotonic transitions while preserving terminal decisions."""
    if desired is ApplicationStatus.UNKNOWN or current == desired:
        return current
    if current is ApplicationStatus.WITHDRAWN:
        return current
    if desired in {ApplicationStatus.OFFER, ApplicationStatus.REJECTED}:
        return desired
    if current in {ApplicationStatus.OFFER, ApplicationStatus.REJECTED}:
        return current
    ranks = {
        ApplicationStatus.UNKNOWN: 0,
        ApplicationStatus.APPLIED: 1,
        ApplicationStatus.ASSESSMENT_PENDING: 2,
        ApplicationStatus.ASSESSMENT_COMPLETED: 3,
        ApplicationStatus.INTERVIEW_PENDING: 4,
        ApplicationStatus.INTERVIEW_SCHEDULED: 5,
        ApplicationStatus.INTERVIEW_COMPLETED: 6,
    }
    return desired if ranks.get(desired, -1) >= ranks.get(current, -1) else current


def action_type_for(evidence: RecruitmentEvidence) -> ActionType:
    mapping = {
        RecruitmentEventType.ASSESSMENT: ActionType.ASSESSMENT,
        RecruitmentEventType.INTERVIEW: ActionType.INTERVIEW,
        RecruitmentEventType.INTERVIEW_RESCHEDULE: ActionType.INTERVIEW,
        RecruitmentEventType.DEADLINE: ActionType.DEADLINE,
        RecruitmentEventType.OFFER: ActionType.OFFER,
        RecruitmentEventType.APPLICATION_RECEIVED: ActionType.APPLICATION_PORTAL,
    }
    return mapping.get(evidence.event_type, ActionType.GENERAL)


def tracked_event_type(event_type: RecruitmentEventType) -> RecruitmentEventType | None:
    if event_type in {RecruitmentEventType.UNKNOWN, RecruitmentEventType.GENERAL_UPDATE}:
        return None
    if event_type is RecruitmentEventType.INTERVIEW_RESCHEDULE:
        return RecruitmentEventType.INTERVIEW
    return event_type


def evidence_allows_mutation(evidence: RecruitmentEvidence) -> tuple[bool, str | None]:
    if (
        evidence.event_type is RecruitmentEventType.INTERVIEW_RESCHEDULE
        and evidence.event_datetime is None
    ):
        return False, "interview_datetime_unresolved"
    if evidence.event_datetime is None and evidence.source_datetime_text is not None:
        return False, "event_datetime_unresolved"
    if evidence.deadline is None and evidence.source_deadline_text is not None:
        return False, "deadline_unresolved"
    if (
        evidence.event_datetime is not None or evidence.deadline is not None
    ) and not evidence.timezone:
        return False, "timezone_unresolved"
    return True, None


def _normalized_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.casefold().split())
    return normalized or None
