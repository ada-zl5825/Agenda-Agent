from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from recruitment_agent.api.app import create_app
from recruitment_agent.api.dependencies import (
    get_authorization_service,
    get_web_session_manager,
)
from recruitment_agent.microsoft.auth_contracts import AuthorizationCompletion, AuthorizationStart
from recruitment_agent.web.security import WebSessionManager


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


class AuthorizationService:
    def __init__(self) -> None:
        self.connection_id = uuid4()
        self.callback: dict[str, str] | None = None

    async def start_authorization(self) -> AuthorizationStart:
        return AuthorizationStart(
            authorization_url="https://login.microsoftonline.com/authorize?opaque=1",
            expires_at=datetime(2026, 8, 12, tzinfo=UTC),
        )

    async def complete_authorization(
        self,
        auth_response: dict[str, str],
    ) -> AuthorizationCompletion:
        self.callback = auth_response
        return AuthorizationCompletion(
            connection_id=self.connection_id,
            home_account_id="opaque-account",
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
    assert callback.headers["location"] == "/reviews"
    session_cookie = callback.cookies[sessions.cookie_name]
    assert sessions.authenticate(session_cookie).connection_id == service.connection_id
    assert "token" not in callback.text.lower()
    assert service.callback == {"code": "opaque-code", "state": "opaque-state"}
