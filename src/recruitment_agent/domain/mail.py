"""Provider-neutral email evidence and synchronization state."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.time import require_aware, require_optional_aware


class MailSyncStatus(StrEnum):
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SourceEmailProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceEmailCandidate:
    """Privacy-minimized message metadata ready for idempotent ingestion."""

    graph_message_id: str
    internet_message_id: str | None
    subject: str
    sender_domain: str | None
    received_at: datetime
    outlook_web_link: str | None
    has_attachments: bool
    body_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.graph_message_id.strip():
            msg = "graph_message_id must not be empty"
            raise DomainValidationError(msg)
        require_aware(self.received_at, field_name="received_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceEmail:
    """Persisted email evidence; raw bodies and attachments are deliberately absent."""

    id: UUID
    account_id: UUID
    graph_message_id: str
    internet_message_id: str | None
    subject: str
    sender_domain: str | None
    received_at: datetime
    outlook_web_link: str | None
    body_hash: str | None
    has_attachments: bool
    processing_status: SourceEmailProcessingStatus
    application_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MailSyncState:
    """Durable cursor and audit state for one account folder."""

    account_id: UUID
    folder_id: str
    delta_link: str | None
    last_sync_started_at: datetime | None
    last_sync_finished_at: datetime | None
    status: MailSyncStatus
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.folder_id.strip():
            msg = "folder_id must not be empty"
            raise DomainValidationError(msg)
        require_optional_aware(
            self.last_sync_started_at,
            field_name="last_sync_started_at",
        )
        require_optional_aware(
            self.last_sync_finished_at,
            field_name="last_sync_finished_at",
        )
