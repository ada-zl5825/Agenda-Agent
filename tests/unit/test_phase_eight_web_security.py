from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from recruitment_agent.application.errors import (
    CsrfValidationError,
    ReviewAuthenticationError,
)
from recruitment_agent.web.security import WebSessionManager


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 13, 8, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def test_signed_session_expires_and_rejects_tampering() -> None:
    clock = Clock()
    account_id = uuid4()
    manager = WebSessionManager(key=b"s" * 32, clock=clock, ttl_seconds=600)

    token = manager.issue(
        account_id,
        admin_home_account_id="admin-account",
        admin_tenant_id="tenant",
    )

    assert manager.authenticate(token).connection_id == account_id
    assert manager.authenticate(token).admin_home_account_id == "admin-account"
    with pytest.raises(ReviewAuthenticationError):
        manager.authenticate(token + "tampered")
    clock.value += timedelta(minutes=10)
    with pytest.raises(ReviewAuthenticationError, match="expired"):
        manager.authenticate(token)


def test_csrf_is_bound_to_session_review_and_version() -> None:
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    review_id = uuid4()
    session = manager.issue(
        uuid4(),
        admin_home_account_id="admin-account",
        admin_tenant_id=None,
    )
    token = manager.csrf_token(
        session_token=session,
        review_id=review_id,
        version=2,
    )

    manager.verify_csrf(
        session_token=session,
        review_id=review_id,
        version=2,
        supplied=token,
    )
    with pytest.raises(CsrfValidationError):
        manager.verify_csrf(
            session_token=session,
            review_id=review_id,
            version=3,
            supplied=token,
        )


def test_action_csrf_is_bound_to_typed_action_and_version() -> None:
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    session = manager.issue(
        uuid4(),
        admin_home_account_id="admin-account",
        admin_tenant_id=None,
    )
    token = manager.action_csrf_token(
        session_token=session,
        action="operation:mail_sync",
        version=2,
    )

    manager.verify_action_csrf(
        session_token=session,
        action="operation:mail_sync",
        version=2,
        supplied=token,
    )
    with pytest.raises(CsrfValidationError):
        manager.verify_action_csrf(
            session_token=session,
            action="operation:send_daily_brief",
            version=2,
            supplied=token,
        )


def test_signed_return_path_prevents_open_redirects() -> None:
    clock = Clock()
    manager = WebSessionManager(key=b"s" * 32, clock=clock)

    token = manager.issue_return_path("https://attacker.example/path")
    valid = manager.issue_return_path("/reviews/00000000-0000-0000-0000-000000000001")

    assert manager.read_return_path(token) == "/agent"
    assert manager.read_return_path(valid).startswith("/reviews/")
    assert manager.read_return_path(valid + "x") == "/agent"
    clock.value += timedelta(minutes=10)
    assert manager.read_return_path(valid) == "/agent"
