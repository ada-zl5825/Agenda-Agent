"""Provider-neutral contracts persisted by the Phase 5/6 workflow."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from recruitment_agent.domain.time import require_aware
from recruitment_agent.extraction.models import (
    ExtractionValidationResult,
    RecruitmentExtraction,
)

COMBINED_DATETIME_REASON = "timezone_and_datetime"
COMBINED_DEADLINE_REASON = "timezone_and_deadline"
COMBINED_TIME_REASONS = frozenset(
    {COMBINED_DATETIME_REASON, COMBINED_DEADLINE_REASON}
)

_REVIEW_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


class WorkflowStage(StrEnum):
    LOAD_SOURCE_EMAIL = "load_source_email"
    NORMALIZE_EMAIL = "normalize_email"
    EXTRACT_ACTION_LINKS = "extract_action_links"
    PREFILTER_RECRUITMENT = "prefilter_recruitment"
    SANITIZE_CONTENT = "sanitize_content"
    EXTRACT_RECRUITMENT_DATA = "extract_recruitment_data"
    VALIDATE_EXTRACTION = "validate_extraction"
    REQUEST_REVIEW = "request_review"
    RESOLVE_APPLICATION = "resolve_application"
    RESOLVE_EXISTING_EVENT = "resolve_existing_event"
    PLAN_STATE_TRANSITION = "plan_state_transition"
    PERSIST_DOMAIN_CHANGES = "persist_domain_changes"
    # The stable node value is retained so Phase 5/6 PostgreSQL checkpoints resume.
    SYNC_CALENDAR = "sync_calendar_placeholder"
    SYNC_CALENDAR_PLACEHOLDER = "sync_calendar_placeholder"
    FINALIZE_PROCESSING = "finalize_processing"
    MARK_IGNORED = "mark_ignored"


class WorkflowPrefilterDecision(StrEnum):
    LIKELY_RECRUITMENT = "likely_recruitment"
    UNKNOWN = "unknown"
    UNLIKELY = "unlikely"


class ProcessingRunStatus(StrEnum):
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    IGNORED = "ignored"
    FAILED = "failed"


class ReviewType(StrEnum):
    TIMEZONE_AMBIGUITY = "TIMEZONE_AMBIGUITY"
    APPLICATION_AMBIGUITY = "APPLICATION_AMBIGUITY"
    DATETIME_CONFLICT = "DATETIME_CONFLICT"
    UNCERTAIN_RESCHEDULE = "UNCERTAIN_RESCHEDULE"
    UNSAFE_CALENDAR_UPDATE = "UNSAFE_CALENDAR_UPDATE"


class ReviewStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class SafePreparedEmail(BaseModel):
    """Checkpoint-safe output of the transient Phase 2/3 preparation pipeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_email_id: UUID
    sender_domain: str | None
    received_at: datetime
    sanitized_text: str = Field(repr=False)
    link_refs: tuple[str, ...]
    prefilter_decision: WorkflowPrefilterDecision

    @field_validator("received_at")
    @classmethod
    def require_aware_received_at(cls, value: datetime) -> datetime:
        require_aware(value, field_name="received_at")
        return value


class CompanyResolutionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_company_name: str | None = Field(repr=False)
    company_id: UUID | None
    status: str
    method: str
    confidence: float = Field(ge=0, le=1)
    matched_value: str | None = Field(repr=False)
    candidate_company_ids: tuple[UUID, ...]


class RoleResolutionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_name: str | None = Field(repr=False)
    normalized_name: str | None = Field(repr=False)
    family: str | None


class WorkflowExtractionResult(BaseModel):
    """Validated, structured evidence safe for checkpoints and audit storage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    extraction: RecruitmentExtraction = Field(repr=False)
    validation: ExtractionValidationResult
    prompt_version: str
    company: CompanyResolutionEvidence | None = Field(repr=False)
    role: RoleResolutionEvidence | None = Field(repr=False)
    company_resolution_audit_id: UUID | None

class ReviewRequest(BaseModel):
    """Safe and deterministic question surfaced by a LangGraph interrupt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_type: ReviewType
    reason: str
    question: str
    allowed_choices: tuple[str, ...]

    @field_validator("reason", "question")
    @classmethod
    def require_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("review text must not be empty")
        return normalized

    @field_validator("allowed_choices")
    @classmethod
    def require_unique_choices(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("allowed choices must be non-empty and unique")
        return value


class ReviewDecision(BaseModel):
    """Typed resume input; it never directly authorizes a domain side effect."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    choice: str
    override_value: str | None = None
    clock_override: str | None = None
    expected_version: int = Field(default=1, ge=1)

    @field_validator("choice")
    @classmethod
    def require_choice(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("review choice must not be empty")
        return normalized


def parse_review_datetime(value: str) -> datetime:
    """Parse a human-entered local or aware datetime without inventing a zone."""
    text = value.strip()
    if not text:
        raise ValueError("datetime override must not be empty")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _REVIEW_DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError("datetime override must be YYYY-MM-DD HH:MM")


def validate_review_decision(
    request: ReviewRequest,
    raw_decision: object,
) -> ReviewDecision:
    decision = ReviewDecision.model_validate(raw_decision)
    if decision.choice not in request.allowed_choices:
        raise ValueError("review choice is not allowed")
    if request.reason in COMBINED_TIME_REASONS:
        if decision.choice == "ignore":
            if decision.override_value is not None or decision.clock_override is not None:
                raise ValueError("ignore cannot include overrides")
            return decision
        if decision.clock_override is None:
            raise ValueError("start or deadline clock is required")
        parse_review_datetime(decision.clock_override)
        if decision.choice == "other":
            if decision.override_value is None:
                raise ValueError("other review choice requires an override value")
            try:
                ZoneInfo(decision.override_value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("timezone override must be a valid IANA timezone") from exc
        elif decision.override_value is not None:
            raise ValueError("override value is only allowed for the other choice")
        return decision
    if decision.clock_override is not None:
        raise ValueError("clock override is only allowed for combined time review")
    if request.review_type is ReviewType.DATETIME_CONFLICT and decision.choice == "use_override":
        if decision.override_value is None:
            raise ValueError("datetime override is required")
        parse_review_datetime(decision.override_value)
        return decision
    if decision.choice == "other":
        if decision.override_value is None:
            raise ValueError("other review choice requires an override value")
        try:
            ZoneInfo(decision.override_value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone override must be a valid IANA timezone") from exc
    elif decision.override_value is not None:
        raise ValueError("override value is only allowed for the other choice")
    return decision


_REVIEW_NAMESPACE = UUID("71eeb0e4-09c1-4a13-b0f0-dd1f26d7b344")
_EXTRACTION_NAMESPACE = UUID("727d64e0-b04f-4e3a-8325-07659797b896")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessingRun:
    id: UUID
    source_email_id: UUID
    graph_thread_id: str
    current_stage: WorkflowStage
    status: ProcessingRunStatus
    prompt_version: str
    model_deployment: str | None
    started_at: datetime

    def __post_init__(self) -> None:
        if not self.graph_thread_id.strip() or not self.prompt_version.strip():
            raise ValueError("processing run identifiers must not be empty")
        require_aware(self.started_at, field_name="started_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewItem:
    id: UUID
    processing_run_id: UUID
    request: ReviewRequest
    status: ReviewStatus
    version: int
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        processing_run_id: UUID,
        request: ReviewRequest,
        created_at: datetime,
    ) -> "ReviewItem":
        require_aware(created_at, field_name="created_at")
        identity = (
            f"{processing_run_id}:{request.review_type.value}:{request.reason}"
        )
        return cls(
            id=uuid5(_REVIEW_NAMESPACE, identity),
            processing_run_id=processing_run_id,
            request=request,
            status=ReviewStatus.OPEN,
            version=1,
            created_at=created_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtractionAudit:
    id: UUID
    processing_run_id: UUID
    source_email_id: UUID
    result: WorkflowExtractionResult
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        processing_run_id: UUID,
        source_email_id: UUID,
        result: WorkflowExtractionResult,
        created_at: datetime,
    ) -> "ExtractionAudit":
        require_aware(created_at, field_name="created_at")
        return cls(
            id=uuid5(_EXTRACTION_NAMESPACE, str(processing_run_id)),
            processing_run_id=processing_run_id,
            source_email_id=source_email_id,
            result=result,
            created_at=created_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowSourceEmail:
    """Provider identity loaded atomically from the source-email record."""

    id: UUID
    account_id: UUID
    graph_message_id: str

    def __post_init__(self) -> None:
        if not self.graph_message_id.strip():
            raise ValueError("graph message ID must not be empty")
