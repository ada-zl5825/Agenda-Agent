from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from recruitment_agent.api.app import create_app
from recruitment_agent.api.briefs import get_brief_renderer
from recruitment_agent.api.dependencies import get_web_session_manager
from recruitment_agent.briefs.renderer import RenderedBrief
from recruitment_agent.web.security import WebSessionManager


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_brief_preview_requires_the_authenticated_microsoft_connection() -> None:
    account_id = uuid4()
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    rendered_for: list[object] = []

    async def render(*, account_id: object) -> RenderedBrief:
        rendered_for.append(account_id)
        return RenderedBrief(subject="Brief", html="<h1>Recruitment Brief</h1>", text="Brief")

    application = create_app()
    application.dependency_overrides[get_web_session_manager] = lambda: manager
    application.dependency_overrides[get_brief_renderer] = lambda: render
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://agent.example",
        follow_redirects=False,
    ) as client:
        unauthenticated = await client.get("/brief/today")
        client.cookies.set(
            manager.cookie_name,
            manager.issue(
                account_id,
                admin_home_account_id="admin-account",
                admin_tenant_id=None,
            ),
        )
        authenticated = await client.get("/brief/today")

    assert unauthenticated.status_code == 303
    assert unauthenticated.headers["location"] == "/auth/login?return_to=/brief/today"
    assert authenticated.status_code == 200
    assert authenticated.text == "<h1>Recruitment Brief</h1>"
    assert rendered_for == [account_id]
