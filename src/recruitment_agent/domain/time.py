"""Shared time invariants.

Normalized datetimes must be timezone-aware. Unresolved source times stay as
source text and enter human review in later phases.
"""

from datetime import datetime

from recruitment_agent.domain.errors import DomainValidationError


def require_aware(value: datetime, *, field_name: str) -> None:
    """Reject normalized datetimes that lack an effective UTC offset."""
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{field_name} must be timezone-aware"
        raise DomainValidationError(msg)


def require_optional_aware(value: datetime | None, *, field_name: str) -> None:
    """Validate an optional normalized datetime."""
    if value is not None:
        require_aware(value, field_name=field_name)
