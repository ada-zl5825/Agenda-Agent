"""Stable domain vocabulary persisted as strings."""

from enum import StrEnum


class ApplicationStatus(StrEnum):
    UNKNOWN = "unknown"
    APPLIED = "applied"
    ASSESSMENT_PENDING = "assessment_pending"
    ASSESSMENT_COMPLETED = "assessment_completed"
    INTERVIEW_PENDING = "interview_pending"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    INTERVIEW_COMPLETED = "interview_completed"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class RecruitmentEventType(StrEnum):
    APPLICATION_RECEIVED = "application_received"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    INTERVIEW_RESCHEDULE = "interview_reschedule"
    ACTION_REQUIRED = "action_required"
    DEADLINE = "deadline"
    RESULT = "result"
    OFFER = "offer"
    REJECTION = "rejection"
    GENERAL_UPDATE = "general_update"
    UNKNOWN = "unknown"


class EventStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class ActionType(StrEnum):
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    CONFIRMATION = "confirmation"
    SCHEDULING = "scheduling"
    APPLICATION_PORTAL = "application_portal"
    OFFER = "offer"
    DEADLINE = "deadline"
    GENERAL = "general"


class ActionStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"
