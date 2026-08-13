from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
import respx

from recruitment_agent.application.errors import CalendarEventNotFoundError
from recruitment_agent.calendar.models import CalendarEventDraft
from recruitment_agent.microsoft.calendar import GraphCalendarClient

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000711")


class TokenProvider:
    def __init__(self) -> None:
        self.refreshes: list[bool] = []

    async def get_access_token(
        self,
        *,
        connection_id: UUID,
        force_refresh: bool = False,
    ) -> str:
        assert connection_id == ACCOUNT_ID
        self.refreshes.append(force_refresh)
        return "refreshed-token" if force_refresh else "cached-token"


def draft() -> CalendarEventDraft:
    start = datetime(2026, 8, 20, 13, tzinfo=UTC)
    return CalendarEventDraft(
        subject="Nimbus | Engineer | Interview 1",
        body="Managed by Recruitment Inbox Agent",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        content_fingerprint="a" * 64,
        transaction_id="56a03653-e591-44d9-bffa-498a5783d1dd",
    )


@pytest.mark.asyncio
@respx.mock
async def test_create_sends_private_text_event_and_transaction_id() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/calendar/events"
    route = respx.post(endpoint).mock(
        return_value=httpx.Response(201, json={"id": "immutable-event-1"})
    )
    async with httpx.AsyncClient() as http_client:
        result = await GraphCalendarClient(
            http_client=http_client,
            token_provider=TokenProvider(),
        ).create_event(account_id=ACCOUNT_ID, draft=draft())

    payload = route.calls[0].request.content.decode()
    assert result.event_id == "immutable-event-1"
    assert '"contentType":"text"' in payload
    assert '"timeZone":"UTC"' in payload
    assert '"transactionId"' in payload
    assert route.calls[0].request.headers["Prefer"] == 'IdType="ImmutableId"'


@pytest.mark.asyncio
@respx.mock
async def test_update_escapes_event_id_and_omits_create_transaction() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/events/event%2Fone"
    route = respx.patch(endpoint).mock(
        return_value=httpx.Response(200, json={"id": "event/one"})
    )
    async with httpx.AsyncClient() as http_client:
        await GraphCalendarClient(
            http_client=http_client,
            token_provider=TokenProvider(),
        ).update_event(account_id=ACCOUNT_ID, event_id="event/one", draft=draft())

    assert route.called
    assert b"transactionId" not in route.calls[0].request.content


@pytest.mark.asyncio
@respx.mock
async def test_update_404_has_typed_reviewable_failure() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/events/missing"
    respx.patch(endpoint).mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as http_client:
        client = GraphCalendarClient(
            http_client=http_client,
            token_provider=TokenProvider(),
        )
        with pytest.raises(CalendarEventNotFoundError):
            await client.update_event(
                account_id=ACCOUNT_ID,
                event_id="missing",
                draft=draft(),
            )


@pytest.mark.asyncio
@respx.mock
async def test_calendar_retry_refreshes_401_and_obeys_retry_after() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/calendar/events"
    respx.post(endpoint).mock(
        side_effect=[
            httpx.Response(401),
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(201, json={"id": "immutable-event-1"}),
        ]
    )
    provider = TokenProvider()
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient() as http_client:
        await GraphCalendarClient(
            http_client=http_client,
            token_provider=provider,
            sleep=record_sleep,
        ).create_event(account_id=ACCOUNT_ID, draft=draft())

    assert provider.refreshes == [False, True, False]
    assert delays == [2.0]
