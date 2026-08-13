import json
from uuid import UUID, uuid4

import httpx
import pytest

from recruitment_agent.application.errors import BriefSendUncertainError
from recruitment_agent.briefs.renderer import RenderedBrief
from recruitment_agent.microsoft.send_mail import GraphBriefMailClient


class Tokens:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, bool]] = []

    async def get_access_token(
        self,
        *,
        connection_id: UUID,
        force_refresh: bool = False,
    ) -> str:
        self.calls.append((connection_id, force_refresh))
        return "opaque-access-token"


@pytest.mark.asyncio
async def test_graph_send_mail_contract_uses_html_and_mail_send_endpoint() -> None:
    account_id = uuid4()
    tokens = Tokens()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/me/sendMail"
        assert request.headers["Authorization"] == "Bearer opaque-access-token"
        payload = json.loads(request.content)
        assert payload == {
            "message": {
                "subject": "Recruitment Brief | 2026-08-13",
                "body": {"contentType": "HTML", "content": "<p>safe</p>"},
                "toRecipients": [{"emailAddress": {"address": "me@example.test"}}],
            },
            "saveToSentItems": True,
        }
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await GraphBriefMailClient(http_client=http, token_provider=tokens).send_brief(
            account_id=account_id,
            recipient="me@example.test",
            brief=RenderedBrief(
                subject="Recruitment Brief | 2026-08-13",
                html="<p>safe</p>",
                text="safe",
            ),
        )

    assert tokens.calls == [(account_id, False)]


@pytest.mark.asyncio
async def test_graph_server_error_is_uncertain_and_is_not_retried() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(BriefSendUncertainError):
            await GraphBriefMailClient(http_client=http, token_provider=Tokens()).send_brief(
                account_id=uuid4(),
                recipient="me@example.test",
                brief=RenderedBrief(subject="Brief", html="<p>safe</p>", text="safe"),
            )

    assert attempts == 1


@pytest.mark.asyncio
async def test_graph_refreshes_once_and_retries_a_definitive_throttle() -> None:
    account_id = uuid4()
    tokens = Tokens()
    statuses = iter((401, 429, 202))
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        headers = {"Retry-After": "2"} if status == 429 else {}
        return httpx.Response(status, headers=headers)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await GraphBriefMailClient(
            http_client=http,
            token_provider=tokens,
            sleep=sleep,
        ).send_brief(
            account_id=account_id,
            recipient="me@example.test",
            brief=RenderedBrief(subject="Brief", html="<p>safe</p>", text="safe"),
        )

    assert tokens.calls == [
        (account_id, False),
        (account_id, True),
        (account_id, False),
    ]
    assert delays == [2.0]
