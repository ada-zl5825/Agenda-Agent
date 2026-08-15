"""Provider-neutral Phase 4 recruitment extraction contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from recruitment_agent.domain.enums import RecruitmentEventType


class RecruitmentExtraction(BaseModel):
    """Strict structured evidence returned by the semantic extraction model.

    Nullable fields are still required in the JSON schema so the model must make
    uncertainty explicit. Values are evidence only and never authorize mutations.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    relevant: bool
    company_raw: str | None = Field(repr=False)
    role_raw: str | None = Field(repr=False)
    event_type: RecruitmentEventType
    interview_round: str | None = Field(repr=False)
    action_required: bool
    action_text: str | None = Field(repr=False)
    action_link_ref: str | None
    event_datetime: datetime | None
    deadline: datetime | None
    timezone_explicit: bool
    timezone_text: str | None = Field(repr=False)
    source_datetime_text: str | None = Field(repr=False)
    source_deadline_text: str | None = Field(repr=False)
    meeting_platform: str | None = Field(repr=False)
    location: str | None = Field(repr=False)
    company_confidence: float = Field(ge=0, le=1)
    event_confidence: float = Field(ge=0, le=1)
    datetime_confidence: float = Field(ge=0, le=1)


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class RecruitmentExtractionRequest:
    """Sanitized-only input accepted by a recruitment extraction model."""

    source_email_id: UUID
    received_at: datetime
    sanitized_text: str
    allowed_link_refs: tuple[str, ...]
    prompt_version: str

    def __repr__(self) -> str:
        return (
            "RecruitmentExtractionRequest("
            f"source_email_id={self.source_email_id!r}, "
            f"received_at={self.received_at!r}, "
            f"link_ref_count={len(self.allowed_link_refs)}, "
            f"prompt_version={self.prompt_version!r})"
        )


class ExtractionUsage(BaseModel):
    """Privacy-safe usage telemetry captured at the model boundary.

    Contains only token counts and wall-clock latency; never prompt or
    completion content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)


class ExtractionValidationStatus(StrEnum):
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    INVALID = "invalid"


class ExtractionIssueSeverity(StrEnum):
    REVIEW = "review"
    ERROR = "error"


class ExtractionIssueCode(StrEnum):
    BLANK_EVIDENCE = "blank_evidence"
    EVIDENCE_NOT_FOUND = "evidence_not_found"
    CONFIDENCE_OUT_OF_RANGE = "confidence_out_of_range"
    LOW_CONFIDENCE = "low_confidence"
    IRRELEVANT_FACT_CONFLICT = "irrelevant_fact_conflict"
    UNKNOWN_EVENT = "unknown_event"
    ACTION_TEXT_MISSING = "action_text_missing"
    ACTION_TEXT_CONFLICT = "action_text_conflict"
    MALFORMED_LINK_REF = "malformed_link_ref"
    UNKNOWN_LINK_REF = "unknown_link_ref"
    DATETIME_SOURCE_MISSING = "datetime_source_missing"
    DATETIME_UNRESOLVED = "datetime_unresolved"
    DEADLINE_SOURCE_MISSING = "deadline_source_missing"
    DEADLINE_UNRESOLVED = "deadline_unresolved"
    TIMEZONE_CONFLICT = "timezone_conflict"
    TIMEZONE_AMBIGUOUS = "timezone_ambiguous"
    DATETIME_NOT_AWARE = "datetime_not_aware"
    RESCHEDULE_DATETIME_MISSING = "reschedule_datetime_missing"


class ExtractionValidationIssue(BaseModel):
    """Privacy-safe deterministic validation finding."""

    model_config = ConfigDict(frozen=True)

    code: ExtractionIssueCode
    severity: ExtractionIssueSeverity
    field: str


class ExtractionValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ExtractionValidationStatus
    issues: tuple[ExtractionValidationIssue, ...]

    @property
    def accepted(self) -> bool:
        return self.status is ExtractionValidationStatus.VALID


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class RecruitmentExtractionOutcome:
    extraction: RecruitmentExtraction
    validation: ExtractionValidationResult
    prompt_version: str

    def __repr__(self) -> str:
        return (
            "RecruitmentExtractionOutcome("
            f"event_type={self.extraction.event_type.value!r}, "
            f"validation={self.validation.status.value!r}, "
            f"prompt_version={self.prompt_version!r})"
        )
