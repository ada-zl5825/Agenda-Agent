"""Provider-neutral contracts for transient normalized email content."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PrefilterDecision(StrEnum):
    LIKELY_RECRUITMENT = "likely_recruitment"
    UNKNOWN = "unknown"
    UNLIKELY = "unlikely"


class ForwardedEnvelope(BaseModel):
    """Original-message headers discovered inside a forwarded email body."""

    model_config = ConfigDict(frozen=True)

    sender_name: str | None = Field(default=None, repr=False)
    sender_address: str | None = Field(default=None, repr=False)
    subject: str | None = Field(default=None, repr=False)
    body_text: str = Field(repr=False)
    depth: int = Field(ge=1)


class NormalizedEmail(BaseModel):
    """Short-lived normalized evidence; this model is never persisted as raw content."""

    model_config = ConfigDict(frozen=True)

    source_email_id: UUID
    graph_message_id: str
    internet_message_id: str | None
    subject: str = Field(repr=False)
    sender_name: str | None = Field(default=None, repr=False)
    sender_address: str | None = Field(default=None, repr=False)
    sender_domain: str | None
    outer_sender_name: str | None = Field(default=None, repr=False)
    outer_sender_address: str | None = Field(default=None, repr=False)
    outer_sender_domain: str | None
    received_at: datetime
    body_text: str = Field(repr=False)
    outlook_web_link: str | None = Field(default=None, repr=False)
    has_attachments: bool
    is_forwarded: bool

    @field_validator("received_at")
    @classmethod
    def require_aware_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        return value


class PrefilterResult(BaseModel):
    """Privacy-safe deterministic prefilter decision and matched rule identifiers."""

    model_config = ConfigDict(frozen=True)

    decision: PrefilterDecision
    matched_rules: tuple[str, ...]
