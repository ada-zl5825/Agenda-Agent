"""Typed dataset and result contracts for the benchmark harness.

The golden dataset reuses the production extraction schema so that every
benchmark case is exactly what the deployed model boundary would receive and
what the deterministic validator would judge.
"""

import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from recruitment_agent.domain.company import normalize_company_name
from recruitment_agent.domain.enums import ApplicationStatus, RecruitmentEventType
from recruitment_agent.extraction.models import (
    ExtractionValidationStatus,
    RecruitmentExtraction,
)
from recruitment_agent.graph.contracts import ReviewType, WorkflowPrefilterDecision

_CASE_NAMESPACE = UUID("6a1f9be0-33cb-4b6d-8f2e-0f4a5f7f6d21")
_COMPANY_NAMESPACE = UUID("4d1cf9de-5f2a-4e0a-9c67-b7f6f1f2f7aa")

_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")
_ACTION_LINK_REF = re.compile(r"^ACTION_LINK_[0-9]{2,}$")
_ACTION_LINK_TOKEN = re.compile(r"\bACTION_LINK_[A-Z0-9_]+\b")
# Mirrors the production model boundary in
# recruitment_agent.application.recruitment_extraction: benchmark inputs must
# satisfy the same sanitization guarantees as live traffic.
_PLAINTEXT_URL = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]*://|\bmailto:|\bwww\.)")
_SECRET_QUERY_FRAGMENT = re.compile(
    r"(?i)(?:[?&]|\b)(?:access_token|auth|code|key|sig|signature|token)="
)


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class BenchmarkCaseInput(BaseModel):
    """Sanitized-only model input; the privacy bar equals production."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    received_at: datetime
    sanitized_text: str = Field(min_length=1)
    allowed_link_refs: tuple[str, ...] = ()
    sender_domain: str | None = None
    prefilter_decision: WorkflowPrefilterDecision = WorkflowPrefilterDecision.LIKELY_RECRUITMENT

    @field_validator("received_at")
    @classmethod
    def require_aware_received_at(cls, value: datetime) -> datetime:
        return _require_aware(value, field_name="received_at")

    @field_validator("allowed_link_refs")
    @classmethod
    def require_valid_link_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("allowed link references must be unique")
        for ref in value:
            if _ACTION_LINK_REF.fullmatch(ref) is None:
                raise ValueError("allowed link references must match ACTION_LINK_NN")
        return value

    @model_validator(mode="after")
    def enforce_sanitized_boundary(self) -> "BenchmarkCaseInput":
        text = self.sanitized_text
        if _PLAINTEXT_URL.search(text) or _SECRET_QUERY_FRAGMENT.search(text):
            raise ValueError("sanitized_text contains a forbidden URL fragment")
        evidence_refs = set(_ACTION_LINK_TOKEN.findall(text))
        if any(_ACTION_LINK_REF.fullmatch(ref) is None for ref in evidence_refs):
            raise ValueError("sanitized_text contains a malformed link reference")
        if not evidence_refs.issubset(self.allowed_link_refs):
            raise ValueError("sanitized_text references a link outside allowed_link_refs")
        return self


class ExpectedExtraction(BaseModel):
    """Field-level golden labels plus the expected deterministic validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relevant: bool
    event_type: RecruitmentEventType
    company_raw: str | None
    role_raw: str | None
    action_required: bool
    action_link_ref: str | None
    event_datetime: datetime | None
    deadline: datetime | None
    timezone_explicit: bool
    validation_status: ExtractionValidationStatus
    validation_issues: tuple[str, ...] = ()

    @field_validator("event_datetime", "deadline")
    @classmethod
    def require_aware_datetimes(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware(value, field_name="expected datetime")


class PipelineOutcome(StrEnum):
    COMPLETED = "completed"
    IGNORED = "ignored"
    NEEDS_REVIEW = "needs_review"


class ExpectedDomainEvent(BaseModel):
    """One expected recruitment-event row after a completed workflow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: RecruitmentEventType
    starts_at: datetime | None = None
    deadline_at: datetime | None = None
    timezone: str | None = None

    @field_validator("starts_at", "deadline_at")
    @classmethod
    def require_aware_datetimes(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware(value, field_name="expected event datetime")


class ExpectedDomainOutcome(BaseModel):
    """Golden final domain state asserted by the pipeline suite."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: PipelineOutcome
    review_type: ReviewType | None = None
    application_status: ApplicationStatus | None = None
    event: ExpectedDomainEvent | None = None
    action_item_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_shape(self) -> "ExpectedDomainOutcome":
        if self.outcome is PipelineOutcome.NEEDS_REVIEW:
            if self.review_type is None:
                raise ValueError("needs_review outcome requires a review_type")
            if self.application_status is not None or self.event is not None:
                raise ValueError("needs_review outcome cannot assert final domain rows")
        else:
            if self.review_type is not None:
                raise ValueError("review_type is only allowed for needs_review")
            if self.outcome is PipelineOutcome.COMPLETED:
                if self.application_status is None:
                    raise ValueError("completed outcome requires an application_status")
            elif (
                self.application_status is not None
                or self.event is not None
                or self.action_item_count != 0
            ):
                raise ValueError("ignored outcome cannot assert domain rows")
        return self


class BenchmarkCase(BaseModel):
    """One golden case: sanitized input, reference output, and expectations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    tags: tuple[str, ...] = Field(min_length=1)
    input: BenchmarkCaseInput
    recorded_response: RecruitmentExtraction
    expected: ExpectedExtraction
    expected_domain: ExpectedDomainOutcome | None = None

    @field_validator("case_id")
    @classmethod
    def require_valid_case_id(cls, value: str) -> str:
        if _CASE_ID.fullmatch(value) is None:
            raise ValueError("case_id must be lowercase snake_case (3-80 chars)")
        return value

    @field_validator("tags")
    @classmethod
    def require_unique_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("tags must be unique")
        return value

    @model_validator(mode="after")
    def validate_link_ref_consistency(self) -> "BenchmarkCase":
        allowed = set(self.input.allowed_link_refs)
        for label, ref in (
            ("recorded_response", self.recorded_response.action_link_ref),
            ("expected", self.expected.action_link_ref),
        ):
            if ref is not None and ref not in allowed:
                raise ValueError(f"{label}.action_link_ref is not an allowed link ref")
        return self

    @property
    def source_email_id(self) -> UUID:
        return uuid5(_CASE_NAMESPACE, f"source:{self.case_id}")

    @property
    def processing_run_id(self) -> UUID:
        return uuid5(_CASE_NAMESPACE, f"run:{self.case_id}")


class CompanySeedSpec(BaseModel):
    """Deterministic company catalog entry seeded before the pipeline suite."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_name: str = Field(min_length=1)
    display_name: str | None = None
    aliases: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()

    @property
    def company_id(self) -> UUID:
        return uuid5(_COMPANY_NAMESPACE, normalize_company_name(self.canonical_name))


class DatasetManifest(BaseModel):
    """Versioned identity of one golden dataset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str = Field(min_length=1)
    version: str = Field(pattern=r"^v[0-9]+$")
    prompt_version: str = Field(min_length=1)
    case_count: int = Field(ge=1)
    description: str = ""


class BenchmarkDataset(BaseModel):
    """A fully validated dataset ready for suite execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: DatasetManifest
    cases: tuple[BenchmarkCase, ...]
    companies: tuple[CompanySeedSpec, ...] = ()

    def filtered(
        self,
        *,
        tags: frozenset[str] | None = None,
        limit: int | None = None,
    ) -> tuple[BenchmarkCase, ...]:
        selected = self.cases
        if tags:
            selected = tuple(case for case in selected if tags.intersection(case.tags))
        if limit is not None:
            selected = selected[:limit]
        return selected
