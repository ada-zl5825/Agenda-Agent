"""Provider-neutral calendar synchronization contracts."""

from recruitment_agent.calendar.models import (
    CalendarCandidate,
    CalendarEventDraft,
    CalendarLinkSnapshot,
    CalendarProviderEvent,
    CalendarSyncOperation,
    CalendarSyncRequest,
    CalendarSyncResult,
)

__all__ = [
    "CalendarCandidate",
    "CalendarEventDraft",
    "CalendarLinkSnapshot",
    "CalendarProviderEvent",
    "CalendarSyncOperation",
    "CalendarSyncRequest",
    "CalendarSyncResult",
]
