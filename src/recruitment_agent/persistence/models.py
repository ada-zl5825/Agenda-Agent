"""Phase 0 SQLAlchemy models.

The models are persistence representations, not domain entities. Mapping and
repository implementations are added alongside concrete use cases.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from recruitment_agent.domain.enums import ActionStatus, ApplicationStatus, EventStatus
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


class ApplicationModel(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint("length(company_name) > 0", name="company_name_not_empty"),
        Index("ix_applications_normalized_identity", "company_normalized", "role_normalized"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
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
    source_email_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
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
    source_email_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
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
    source_email_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    secure_link_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ActionStatus.OPEN.value,
        server_default=text("'open'"),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
