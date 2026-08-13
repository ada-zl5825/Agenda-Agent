"""Privacy-minimized provider-neutral Daily Brief read models."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import SecretStr


class BriefSection(StrEnum):
    TODAY = "TODAY"
    NEXT_48_HOURS = "NEXT 48 HOURS"
    ASSESSMENTS = "ASSESSMENTS"
    UPCOMING_INTERVIEWS = "UPCOMING INTERVIEWS"
    ACTION_REQUIRED = "ACTION REQUIRED"
    NEW_UPDATES = "NEW UPDATES"
    WAITING_FOR_RESULT = "WAITING FOR RESULT"
    NEEDS_REVIEW = "NEEDS REVIEW"


SECTION_ORDER: tuple[BriefSection, ...] = tuple(BriefSection)


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class BriefItem:
    identity: str
    section: BriefSection
    company: str | None
    role: str | None
    stage: str
    starts_at: datetime | None = None
    deadline_at: datetime | None = None
    timezone: str | None = None
    detail: str | None = None
    original_email_url: str | None = None
    secure_link_id: UUID | None = None
    action_label: str | None = None
    action_url: SecretStr | None = None
    review_id: UUID | None = None
    review_url: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class DailyBriefSnapshot:
    account_id: UUID
    brief_date: date
    timezone: str
    generated_at: datetime
    items: tuple[BriefItem, ...]

    def __repr__(self) -> str:
        return (
            "DailyBriefSnapshot("
            f"account_id={self.account_id!r}, brief_date={self.brief_date!r}, "
            f"item_count={len(self.items)})"
        )
