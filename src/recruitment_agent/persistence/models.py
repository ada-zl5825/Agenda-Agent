"""Phase 0 SQLAlchemy models.

The models are persistence representations, not domain entities. Mapping and
repository implementations are added alongside concrete use cases.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from recruitment_agent.domain.enums import ActionStatus, ApplicationStatus, EventStatus
from recruitment_agent.domain.mail import MailSyncStatus, SourceEmailProcessingStatus
from recruitment_agent.persistence.base import Base


class TimestampMixin:
    """Database-managed timezone-aware creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MicrosoftConnectionModel(TimestampMixin, Base):
    """One delegated Microsoft identity with an encrypted serialized MSAL cache."""

    __tablename__ = "microsoft_connections"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    home_account_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64))
    token_cache_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_cache_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_cache_key_version: Mapped[str | None] = mapped_column(String(64))
    token_cache_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )


class MicrosoftAuthorizationFlowModel(Base):
    """Single-use, encrypted authorization-code flow state."""

    __tablename__ = "microsoft_authorization_flows"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "app.microsoft_connections.id",
            ondelete="CASCADE",
            name="fk_ms_auth_flows_connection",
        ),
        nullable=False,
        index=True,
    )
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    flow_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    flow_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MailSyncStateModel(TimestampMixin, Base):
    """Durable Graph delta cursor for one connection and folder."""

    __tablename__ = "mail_sync_states"
    __table_args__ = (
        UniqueConstraint("account_id", "folder_id", name="uq_mail_sync_states_account_folder"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.microsoft_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    delta_link: Mapped[str | None] = mapped_column(Text)
    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MailSyncStatus.IDLE.value,
        server_default=text("'idle'"),
    )
    error_code: Mapped[str | None] = mapped_column(String(64))


class SourceEmailModel(TimestampMixin, Base):
    """Privacy-minimized evidence record; body and attachment columns are forbidden."""

    __tablename__ = "source_emails"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.microsoft_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    graph_message_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    internet_message_id: Mapped[str | None] = mapped_column(String(512), index=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    sender_domain: Mapped[str | None] = mapped_column(String(255))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    outlook_web_link: Mapped[str | None] = mapped_column(Text)
    body_hash: Mapped[str | None] = mapped_column(String(64))
    has_attachments: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    processing_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SourceEmailProcessingStatus.PENDING.value,
        server_default=text("'pending'"),
        index=True,
    )
    application_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.applications.id", ondelete="SET NULL"),
        index=True,
    )


class SecureLinkModel(TimestampMixin, Base):
    """Encrypted external destination with safe display metadata only."""

    __tablename__ = "secure_links"
    __table_args__ = (
        UniqueConstraint("source_email_id", "ref", name="uq_secure_links_source_email_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_email_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.source_emails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ref: Mapped[str] = mapped_column(String(32), nullable=False)
    link_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_url: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(128), nullable=False)
    display_text: Mapped[str | None] = mapped_column(Text)


class CompanyModel(TimestampMixin, Base):
    """Canonical company identity independent from extraction text."""

    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint("length(canonical_name) > 0", name="canonical_name_not_empty"),
        CheckConstraint(
            "length(normalized_canonical_name) > 0",
            name="normalized_canonical_name_not_empty",
        ),
        CheckConstraint("length(display_name) > 0", name="display_name_not_empty"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_canonical_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    parent_company_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "app.companies.id",
            ondelete="RESTRICT",
            name="fk_companies_parent_company",
        ),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)


class CompanyAliasModel(Base):
    """Exact normalized company name mapped to a canonical identity."""

    __tablename__ = "company_aliases"
    __table_args__ = (
        CheckConstraint("length(alias) > 0", name="alias_not_empty"),
        CheckConstraint("length(normalized_alias) > 0", name="normalized_alias_not_empty"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_company_aliases_normalized_alias", "normalized_alias"),
    )

    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    normalized_alias: Mapped[str] = mapped_column(String(255), primary_key=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class CompanyDomainModel(Base):
    """Exact sender hostname mapped to a canonical identity."""

    __tablename__ = "company_domains"
    __table_args__ = (
        CheckConstraint("length(domain) > 0", name="domain_not_empty"),
        CheckConstraint("domain = lower(domain)", name="domain_lowercase"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_company_domains_domain", "domain"),
    )

    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class CompanyResolutionAttemptModel(Base):
    """Append-only, idempotent evidence for a Phase 4.5 resolution result."""

    __tablename__ = "company_resolution_attempts"
    __table_args__ = (
        CheckConstraint(
            "raw_company_name IS NULL OR length(btrim(raw_company_name)) > 0",
            name="raw_company_name_not_empty",
        ),
        CheckConstraint(
            "matched_value IS NULL OR length(btrim(matched_value)) > 0",
            name="matched_value_not_empty",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "role_raw IS NULL OR length(btrim(role_raw)) > 0",
            name="role_raw_not_empty",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_email_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.source_emails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_domain: Mapped[str | None] = mapped_column(String(255))
    raw_company_name: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.companies.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    matched_value: Mapped[str | None] = mapped_column(String(255))
    role_raw: Mapped[str | None] = mapped_column(Text)
    role_normalized: Mapped[str | None] = mapped_column(Text)
    role_family: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CompanyResolutionCandidateModel(Base):
    """Canonical candidates retained for an ambiguous resolution audit."""

    __tablename__ = "company_resolution_candidates"

    resolution_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.company_resolution_attempts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.companies.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class ProcessingRunModel(Base):
    """Durable audit row for one LangGraph thread."""

    __tablename__ = "processing_runs"
    __table_args__ = (
        CheckConstraint("length(graph_thread_id) > 0", name="graph_thread_id_not_empty"),
        CheckConstraint("length(current_stage) > 0", name="current_stage_not_empty"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_email_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.source_emails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    graph_thread_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    current_stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_deployment: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail_sanitized: Mapped[str | None] = mapped_column(String(255))


class LlmExtractionModel(Base):
    """Validated structured output only; prompts and raw email content are forbidden."""

    __tablename__ = "llm_extractions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    processing_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.processing_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    source_email_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.source_emails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extraction: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    validation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    company_resolution: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    role_resolution: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    company_resolution_audit_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.company_resolution_attempts.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewItemModel(Base):
    """Typed human decision request; no checkpoint payload or private email body."""

    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint("length(reason) > 0", name="reason_not_empty"),
        CheckConstraint("length(question) > 0", name="question_not_empty"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    processing_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.processing_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_choices: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    resolution: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationModel(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            "raw_company_name IS NULL OR length(btrim(raw_company_name)) > 0",
            name="raw_company_name_not_empty",
        ),
        Index("ix_applications_company_role", "company_id", "role_normalized"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "app.companies.id",
            ondelete="RESTRICT",
            name="fk_applications_company",
        ),
        index=True,
    )
    raw_company_name: Mapped[str | None] = mapped_column(String(255))
    role_name: Mapped[str | None] = mapped_column(String(255))
    role_normalized: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ApplicationStatus.UNKNOWN.value,
        server_default=text("'unknown'"),
        index=True,
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default=text("1"))


class ApplicationStatusHistoryModel(Base):
    __tablename__ = "application_status_history"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    source_email_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "app.source_emails.id",
            ondelete="SET NULL",
            name="fk_application_status_history_source_email",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RecruitmentEventModel(TimestampMixin, Base):
    __tablename__ = "recruitment_events"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "semantic_fingerprint",
            name="uq_recruitment_events_application_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    round: Mapped[str | None] = mapped_column(String(100))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str | None] = mapped_column(String(64))
    source_datetime_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EventStatus.ACTIVE.value,
        server_default=text("'active'"),
        index=True,
    )
    semantic_fingerprint: Mapped[str | None] = mapped_column(String(64))


class EventHistoryModel(Base):
    __tablename__ = "event_history"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    recruitment_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.recruitment_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_timezone: Mapped[str | None] = mapped_column(String(64))
    previous_status: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    source_email_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "app.source_emails.id",
            ondelete="SET NULL",
            name="fk_event_history_source_email",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ActionItemModel(TimestampMixin, Base):
    __tablename__ = "action_items"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "idempotency_key",
            name="uq_action_items_application_idempotency_key",
        ),
        CheckConstraint("length(title) > 0", name="title_not_empty"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app.applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_email_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "app.source_emails.id",
            ondelete="CASCADE",
            name="fk_action_items_source_email",
        ),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    secure_link_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "app.secure_links.id",
            ondelete="SET NULL",
            name="fk_action_items_secure_link",
        ),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ActionStatus.OPEN.value,
        server_default=text("'open'"),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
