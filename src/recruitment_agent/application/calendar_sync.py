"""Deterministic Phase 7 calendar planning and idempotent coordination."""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid5

from recruitment_agent.application.errors import CalendarEventNotFoundError
from recruitment_agent.calendar.models import (
    CalendarCandidate,
    CalendarEventDraft,
    CalendarLinkSnapshot,
    CalendarProviderEvent,
    CalendarSyncOperation,
    CalendarSyncRequest,
    CalendarSyncResult,
)
from recruitment_agent.domain.enums import EventStatus, RecruitmentEventType
from recruitment_agent.domain.ports import Clock

LOGGER = logging.getLogger(__name__)

_CALENDAR_TRANSACTION_NAMESPACE = UUID("30160141-ccde-424e-aa4f-aef60113d2d2")
_URL = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]*://|\bwww\.)")
_OUTLOOK_HOSTS = frozenset(
    {"outlook.office.com", "outlook.office365.com", "outlook.live.com"}
)


class CalendarSyncStore(Protocol):
    async def load_candidate(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        recruitment_event_id: UUID,
    ) -> CalendarCandidate: ...

    async def get_link(
        self,
        recruitment_event_id: UUID,
    ) -> CalendarLinkSnapshot | None: ...

    async def save_link(self, link: CalendarLinkSnapshot) -> None: ...


class CalendarGateway(Protocol):
    async def create_event(
        self,
        *,
        account_id: UUID,
        draft: CalendarEventDraft,
    ) -> CalendarProviderEvent: ...

    async def update_event(
        self,
        *,
        account_id: UUID,
        event_id: str,
        draft: CalendarEventDraft,
    ) -> CalendarProviderEvent: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class CalendarPlan:
    draft: CalendarEventDraft | None
    reason: str
    needs_review: bool = False


class CalendarPlanner:
    """Build Graph-independent safe event content from validated domain state."""

    def __init__(
        self,
        *,
        interview_placeholder_minutes: int = 60,
        assessment_placeholder_minutes: int = 30,
    ) -> None:
        if interview_placeholder_minutes < 1 or assessment_placeholder_minutes < 1:
            raise ValueError("calendar placeholder durations must be positive")
        self._interview_minutes = interview_placeholder_minutes
        self._assessment_minutes = assessment_placeholder_minutes

    def plan(
        self,
        candidate: CalendarCandidate,
        *,
        has_existing_link: bool,
    ) -> CalendarPlan:
        if candidate.event_status is not EventStatus.ACTIVE:
            reason = (
                "inactive_event_has_calendar_link" if has_existing_link else "inactive_event"
            )
            return CalendarPlan(
                draft=None,
                reason=reason,
                needs_review=has_existing_link,
            )
        if not candidate.application_resolved or candidate.company_display_name is None:
            return CalendarPlan(
                draft=None,
                reason="application_not_resolved_for_calendar",
                needs_review=True,
            )
        if not candidate.timezone:
            return CalendarPlan(
                draft=None,
                reason="calendar_timezone_unresolved",
                needs_review=True,
            )

        is_interview = candidate.event_type in {
            RecruitmentEventType.INTERVIEW,
            RecruitmentEventType.INTERVIEW_RESCHEDULE,
        }
        is_assessment = candidate.event_type in {
            RecruitmentEventType.ASSESSMENT,
            RecruitmentEventType.DEADLINE,
        }
        if is_interview:
            starts_at = candidate.starts_at
            minutes = self._interview_minutes
            stage = "Interview"
            if candidate.interview_round:
                stage = f"Interview {self._safe_text(candidate.interview_round, limit=60)}"
        elif is_assessment:
            starts_at = candidate.deadline_at
            minutes = self._assessment_minutes
            stage = "Assessment Deadline"
        else:
            return CalendarPlan(draft=None, reason="event_type_not_calendar_eligible")
        if starts_at is None:
            return CalendarPlan(
                draft=None,
                reason="calendar_datetime_unresolved",
                needs_review=True,
            )
        if starts_at.tzinfo is None or starts_at.utcoffset() is None:
            return CalendarPlan(
                draft=None,
                reason="calendar_datetime_not_timezone_aware",
                needs_review=True,
            )

        start_utc = starts_at.astimezone(UTC)
        end_utc = start_utc + timedelta(minutes=minutes)
        company = self._safe_text(candidate.company_display_name, limit=100)
        role = self._safe_text(candidate.role_name or "Recruitment", limit=100)
        subject = self._safe_text(f"{company} | {role} | {stage}", limit=255)
        original_time = self._safe_optional_text(candidate.source_datetime_text, limit=300)
        body_lines = [
            f"Company: {company}",
            f"Role: {role}",
            f"Stage: {stage}",
        ]
        if original_time is not None:
            body_lines.append(f"Original time: {original_time}")
        body_lines.append(
            f"Calendar duration: {minutes}-minute placeholder; verify the original email."
        )
        source = self._safe_outlook_link(candidate.outlook_web_link)
        if source is not None:
            body_lines.append(f"Source: {source}")
        body_lines.append("Managed by Recruitment Inbox Agent")

        fingerprint_input = {
            "subject": subject,
            "body": body_lines,
            "start": start_utc.isoformat(),
            "end": end_utc.isoformat(),
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_input,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        transaction_id = str(
            uuid5(
                _CALENDAR_TRANSACTION_NAMESPACE,
                f"{candidate.recruitment_event_id}:{fingerprint}",
            )
        )
        return CalendarPlan(
            draft=CalendarEventDraft(
                subject=subject,
                body="\n".join(body_lines),
                starts_at=start_utc,
                ends_at=end_utc,
                content_fingerprint=fingerprint,
                transaction_id=transaction_id,
            ),
            reason="calendar_event_ready",
        )

    @staticmethod
    def _safe_text(value: str, *, limit: int) -> str:
        normalized = " ".join(value.split())
        if not normalized or _URL.search(normalized):
            return "Recruitment"
        return normalized[:limit]

    @classmethod
    def _safe_optional_text(cls, value: str | None, *, limit: int) -> str | None:
        if value is None or _URL.search(value):
            return None
        normalized = cls._safe_text(value, limit=limit)
        return None if normalized == "Recruitment" and not value.strip() else normalized

    @staticmethod
    def _safe_outlook_link(value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname not in _OUTLOOK_HOSTS:
            return None
        return urlunsplit(("https", parsed.netloc, parsed.path, "", ""))


class CalendarSyncService:
    """Coordinate deterministic planning, Graph writes, and durable idempotency links."""

    def __init__(
        self,
        *,
        store: CalendarSyncStore,
        gateway: CalendarGateway,
        planner: CalendarPlanner,
        clock: Clock,
        enabled: bool,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._planner = planner
        self._clock = clock
        self._enabled = enabled

    async def sync(self, request: CalendarSyncRequest) -> CalendarSyncResult:
        result = await self._sync(request)
        # Enum, reason code and opaque UUID only; production diagnosis of "why
        # was no calendar event written" is impossible without this line.
        LOGGER.info(
            "calendar_sync_outcome operation=%s reason=%s event=%s",
            result.operation.value,
            result.reason,
            request.recruitment_event_id,
        )
        return result

    async def _sync(self, request: CalendarSyncRequest) -> CalendarSyncResult:
        if not self._enabled:
            return CalendarSyncResult(
                operation=CalendarSyncOperation.DISABLED,
                reason="calendar_sync_disabled",
            )
        if request.skip_update:
            return CalendarSyncResult(
                operation=CalendarSyncOperation.SKIPPED,
                reason="calendar_update_skipped_by_review",
            )
        if request.recruitment_event_id is None:
            return CalendarSyncResult(
                operation=CalendarSyncOperation.SKIPPED,
                reason="no_recruitment_event",
            )

        candidate = await self._store.load_candidate(
            account_id=request.account_id,
            source_email_id=request.source_email_id,
            recruitment_event_id=request.recruitment_event_id,
        )
        link = await self._store.get_link(request.recruitment_event_id)
        plan = self._planner.plan(candidate, has_existing_link=link is not None)
        if plan.needs_review:
            return CalendarSyncResult(
                operation=CalendarSyncOperation.REVIEW_REQUIRED,
                reason=plan.reason,
            )
        if plan.draft is None:
            return CalendarSyncResult(
                operation=CalendarSyncOperation.SKIPPED,
                reason=plan.reason,
            )
        draft = plan.draft

        if link is None or request.replace_missing_event:
            created = await self._gateway.create_event(
                account_id=request.account_id,
                draft=draft,
            )
            await self._save_link(candidate, created, draft)
            return CalendarSyncResult(
                operation=CalendarSyncOperation.CREATED,
                reason=(
                    "missing_calendar_event_replaced"
                    if request.replace_missing_event
                    else "calendar_event_created"
                ),
            )
        if link.account_id != request.account_id or link.provider != "microsoft_graph":
            return CalendarSyncResult(
                operation=CalendarSyncOperation.REVIEW_REQUIRED,
                reason="calendar_link_identity_conflict",
            )
        if link.content_fingerprint == draft.content_fingerprint:
            return CalendarSyncResult(
                operation=CalendarSyncOperation.UNCHANGED,
                reason="calendar_event_already_current",
            )
        try:
            updated = await self._gateway.update_event(
                account_id=request.account_id,
                event_id=link.calendar_event_id,
                draft=draft,
            )
        except CalendarEventNotFoundError:
            return CalendarSyncResult(
                operation=CalendarSyncOperation.REVIEW_REQUIRED,
                reason="linked_calendar_event_missing",
            )
        await self._save_link(candidate, updated, draft)
        return CalendarSyncResult(
            operation=CalendarSyncOperation.UPDATED,
            reason="calendar_event_updated",
        )

    async def _save_link(
        self,
        candidate: CalendarCandidate,
        provider_event: CalendarProviderEvent,
        draft: CalendarEventDraft,
    ) -> None:
        await self._store.save_link(
            CalendarLinkSnapshot(
                recruitment_event_id=candidate.recruitment_event_id,
                account_id=candidate.account_id,
                provider="microsoft_graph",
                calendar_event_id=provider_event.event_id,
                content_fingerprint=draft.content_fingerprint,
                last_synced_at=self._clock.now(),
            )
        )
