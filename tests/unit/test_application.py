from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from recruitment_agent.domain.application import Application
from recruitment_agent.domain.enums import ApplicationStatus
from recruitment_agent.domain.errors import DomainValidationError


def test_application_identity_uses_company_id_and_preserves_raw_name() -> None:
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    company_id = uuid4()
    application = Application(
        id=uuid4(),
        company_id=company_id,
        raw_company_name="  ByteDance 招聘  ",
        role_name="  Backend   Engineer ",
        status=ApplicationStatus.APPLIED,
        created_at=now,
        updated_at=now,
    )

    assert application.raw_company_name == "  ByteDance 招聘  "
    assert application.normalized_identity == (company_id, "backend engineer")
    assert application.company_resolved is True


def test_application_allows_unresolved_company_without_guessing() -> None:
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    application = Application(
        id=uuid4(),
        company_id=None,
        raw_company_name="Unknown Labs",
        role_name=None,
        status=ApplicationStatus.UNKNOWN,
        created_at=now,
        updated_at=now,
    )

    assert application.company_resolved is False
    assert application.normalized_identity == (None, None)


def test_application_rejects_blank_raw_company() -> None:
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)

    with pytest.raises(DomainValidationError, match="raw_company_name"):
        Application(
            id=uuid4(),
            company_id=None,
            raw_company_name="   ",
            role_name=None,
            status=ApplicationStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )


def test_application_rejects_reversed_audit_time() -> None:
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)

    with pytest.raises(DomainValidationError, match="must not precede"):
        Application(
            id=uuid4(),
            company_id=None,
            raw_company_name="Example",
            role_name=None,
            status=ApplicationStatus.UNKNOWN,
            created_at=now,
            updated_at=now - timedelta(seconds=1),
        )
