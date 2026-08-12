from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from recruitment_agent.domain.application import Application
from recruitment_agent.domain.enums import ApplicationStatus
from recruitment_agent.domain.errors import DomainValidationError


def test_application_normalizes_identity() -> None:
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)
    application = Application(
        id=uuid4(),
        company_name="  ByteDance  ",
        role_name="  Backend   Engineer ",
        status=ApplicationStatus.APPLIED,
        created_at=now,
        updated_at=now,
    )

    assert application.company_name == "ByteDance"
    assert application.normalized_identity == ("bytedance", "backend engineer")


def test_application_rejects_empty_company() -> None:
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)

    with pytest.raises(DomainValidationError, match="company_name"):
        Application(
            id=uuid4(),
            company_name="   ",
            role_name=None,
            status=ApplicationStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )


def test_application_rejects_reversed_audit_time() -> None:
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)

    with pytest.raises(DomainValidationError, match="must not precede"):
        Application(
            id=uuid4(),
            company_name="Example",
            role_name=None,
            status=ApplicationStatus.UNKNOWN,
            created_at=now,
            updated_at=now - timedelta(seconds=1),
        )
