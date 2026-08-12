from datetime import UTC, datetime
from uuid import uuid4

import pytest

from recruitment_agent.domain.enums import EventStatus, RecruitmentEventType
from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.event import RecruitmentEvent


def test_event_accepts_explicit_timezone() -> None:
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)
    starts_at = datetime(2026, 8, 20, 7, tzinfo=UTC)

    event = RecruitmentEvent(
        id=uuid4(),
        application_id=uuid4(),
        type=RecruitmentEventType.INTERVIEW,
        status=EventStatus.ACTIVE,
        round="  First round  ",
        starts_at=starts_at,
        timezone="Asia/Shanghai",
        source_datetime_text="北京时间 8 月 20 日 15:00",
        created_at=now,
        updated_at=now,
    )

    assert event.round == "First round"
    assert event.starts_at == starts_at
    assert event.timezone == "Asia/Shanghai"


def test_event_rejects_naive_datetime() -> None:
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)

    with pytest.raises(DomainValidationError, match="starts_at must be timezone-aware"):
        RecruitmentEvent(
            id=uuid4(),
            application_id=uuid4(),
            type=RecruitmentEventType.INTERVIEW,
            status=EventStatus.ACTIVE,
            starts_at=datetime(2026, 8, 20, 15),
            timezone="Asia/Shanghai",
            created_at=now,
            updated_at=now,
        )


def test_event_rejects_normalized_time_without_timezone_evidence() -> None:
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)

    with pytest.raises(DomainValidationError, match="explicit timezone"):
        RecruitmentEvent(
            id=uuid4(),
            application_id=uuid4(),
            type=RecruitmentEventType.INTERVIEW,
            status=EventStatus.ACTIVE,
            starts_at=datetime(2026, 8, 20, 15, tzinfo=UTC),
            timezone=None,
            source_datetime_text="8 月 20 日下午 3 点",
            created_at=now,
            updated_at=now,
        )
