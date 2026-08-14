from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from recruitment_agent.api.app import create_app
from recruitment_agent.api.dependencies import (
    get_authorization_service,
    get_web_session_manager,
)
from recruitment_agent.microsoft.auth_contracts import (
    AuthorizationCompletion,
    AuthorizationPurpose,
    AuthorizationStart,
)
from recruitment_agent.web.security import WebSessionManager


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


class AuthorizationService:
    def __init__(self) -> None:
        self.connection_id = uuid4()
        self.callback: dict[str, str] | None = None
        self.purpose = AuthorizationPurpose.ADMIN_LOGIN
        self.initiated_by: str | None = None

    async def start_admin_authorization(self) -> AuthorizationStart:
        self.purpose = AuthorizationPurpose.ADMIN_LOGIN
        return AuthorizationStart(
            authorization_url="https://login.microsoftonline.com/authorize?opaque=1",
            expires_at=datetime(2026, 8, 12, tzinfo=UTC),
        )

    async def start_mailbox_authorization(self, *, initiated_by: str) -> AuthorizationStart:
        self.purpose = AuthorizationPurpose.MAILBOX_CONNECTION
        self.initiated_by = initiated_by
        return AuthorizationStart(
            authorization_url="https://login.microsoftonline.com/authorize?mailbox=1",
            expires_at=datetime(2026, 8, 12, tzinfo=UTC),
        )

    async def complete_authorization(
        self,
        auth_response: dict[str, str],
        *,
        admin_home_account_id: str | None = None,
    ) -> AuthorizationCompletion:
        self.callback = auth_response
        if self.purpose is AuthorizationPurpose.MAILBOX_CONNECTION:
            assert admin_home_account_id == "admin-account"
        return AuthorizationCompletion(
            connection_id=self.connection_id,
            home_account_id=(
                "mailbox-account"
                if self.purpose is AuthorizationPurpose.MAILBOX_CONNECTION
                else "admin-account"
            ),
            tenant_id="tenant",
            purpose=self.purpose,
        )


@pytest.mark.asyncio
async def test_auth_routes_delegate_without_returning_tokens() -> None:
    application = create_app()
    service = AuthorizationService()
    sessions = WebSessionManager(key=b"s" * 32, clock=Clock())
    application.dependency_overrides[get_authorization_service] = lambda: service
    application.dependency_overrides[get_web_session_manager] = lambda: sessions
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        login = await client.get("/auth/login")
        callback = await client.get("/auth/callback?code=opaque-code&state=opaque-state")

    assert login.status_code == 302
    assert login.headers["location"].startswith("https://login.microsoftonline.com")
    assert callback.status_code == 303
    assert callback.headers["location"] == "/agent"
    session_cookie = callback.cookies[sessions.cookie_name]
    assert sessions.authenticate(session_cookie).connection_id == service.connection_id
    assert sessions.authenticate(session_cookie).admin_home_account_id == "admin-account"
    assert "token" not in callback.text.lower()
    assert service.callback == {"code": "opaque-code", "state": "opaque-state"}


@pytest.mark.asyncio
async def test_mailbox_connection_requires_admin_and_preserves_admin_session() -> None:
    application = create_app()
    service = AuthorizationService()
    sessions = WebSessionManager(key=b"s" * 32, clock=Clock())
    application.dependency_overrides[get_authorization_service] = lambda: service
    application.dependency_overrides[get_web_session_manager] = lambda: sessions
    transport = httpx.ASGITransport(app=application)
    session_token = sessions.issue(
        service.connection_id,
        admin_home_account_id="admin-account",
        admin_tenant_id="tenant",
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        rejected = await client.get("/auth/mailbox/connect")
        client.cookies.set(sessions.cookie_name, session_token)
        started = await client.get("/auth/mailbox/connect")
        completed = await client.get("/auth/callback?code=mailbox&state=state")

    assert rejected.status_code == 303
    assert started.status_code == 302
    assert service.initiated_by == "admin-account"
    assert completed.status_code == 303
    assert completed.headers["location"] == "/agent?notice=mailbox-connected"
    assert sessions.cookie_name not in completed.cookies
