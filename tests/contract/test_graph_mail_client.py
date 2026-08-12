from uuid import UUID, uuid4

import httpx
import pytest
import respx

from recruitment_agent.application.errors import DeltaStateInvalidError, GraphRateLimitedError
from recruitment_agent.microsoft.graph import GraphMailClient


class TokenProvider:
    def __init__(self) -> None:
        self.refreshes: list[bool] = []

    async def get_access_token(
        self,
        *,
        connection_id: UUID,
        force_refresh: bool = False,
    ) -> str:
        del connection_id
        self.refreshes.append(force_refresh)
        return "refreshed-token" if force_refresh else "cached-token"


def message_payload(*, include_body: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "graph-1",
        "internetMessageId": "<mail-1@example.com>",
        "subject": "Interview invitation",
        "from": {"emailAddress": {"address": "recruiter@Example.COM"}},
        "receivedDateTime": "2026-08-12T08:00:00Z",
        "webLink": "https://outlook.office.com/mail/id/graph-1",
        "hasAttachments": True,
    }
    if include_body:
        payload["body"] = {"contentType": "html", "content": "<p>Hello</p>"}
    return payload


@pytest.mark.asyncio
@respx.mock
async def test_initial_delta_uses_metadata_only_and_maps_sender_domain() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta"
    route = respx.get(endpoint).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [message_payload()],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-token",
            },
        )
    )
    provider = TokenProvider()
    async with httpx.AsyncClient() as http_client:
        client = GraphMailClient(http_client=http_client, token_provider=provider)
        page = await client.fetch_delta_page(
            account_id=uuid4(),
            folder_id="inbox",
            cursor=None,
        )

    assert page.messages[0].sender_domain == "example.com"
    assert page.messages[0].body_hash is None
    assert page.delta_link == "https://graph.microsoft.com/v1.0/delta-token"
    request = route.calls[0].request
    assert "body" not in request.url.params["$select"]
    assert request.headers["Authorization"] == "Bearer cached-token"
    assert request.headers["Prefer"] == "odata.maxpagesize=50"


@pytest.mark.asyncio
@respx.mock
async def test_delta_cursor_supports_pagination_without_readding_query_options() -> None:
    cursor = "https://graph.microsoft.com/v1.0/next?%24skiptoken=opaque"
    route = respx.get(cursor).mock(
        return_value=httpx.Response(
            200,
            json={"value": [], "@odata.deltaLink": cursor.replace("next", "delta")},
        )
    )
    async with httpx.AsyncClient() as http_client:
        client = GraphMailClient(http_client=http_client, token_provider=TokenProvider())
        await client.fetch_delta_page(account_id=uuid4(), folder_id="inbox", cursor=cursor)

    assert route.called
    assert route.calls[0].request.url.params["$skiptoken"] == "opaque"
    assert "$select" not in route.calls[0].request.url.params


@pytest.mark.asyncio
@respx.mock
async def test_message_retrieval_keeps_body_transient_and_never_calls_attachment_api() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/messages/graph-1"
    route = respx.get(endpoint).mock(
        return_value=httpx.Response(200, json=message_payload(include_body=True))
    )
    async with httpx.AsyncClient() as http_client:
        client = GraphMailClient(http_client=http_client, token_provider=TokenProvider())
        mail = await client.fetch_message(account_id=uuid4(), message_id="graph-1")

    assert mail.body_content == "<p>Hello</p>"
    assert mail.metadata.body_hash is not None
    assert "body" in route.calls[0].request.url.params["$select"]
    assert all("attachments" not in str(call.request.url) for call in respx.calls)


@pytest.mark.asyncio
@respx.mock
async def test_unauthorized_response_forces_one_token_refresh() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta"
    respx.get(endpoint).mock(
        side_effect=[
            httpx.Response(401),
            httpx.Response(200, json={"value": [], "@odata.deltaLink": endpoint}),
        ]
    )
    provider = TokenProvider()
    async with httpx.AsyncClient() as http_client:
        client = GraphMailClient(http_client=http_client, token_provider=provider)
        await client.fetch_delta_page(account_id=uuid4(), folder_id="inbox", cursor=None)

    assert provider.refreshes == [False, True]


@pytest.mark.asyncio
@respx.mock
async def test_throttling_obeys_retry_after_and_transient_failure_retries() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta"
    respx.get(endpoint).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(503),
            httpx.Response(200, json={"value": [], "@odata.deltaLink": endpoint}),
        ]
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient() as http_client:
        client = GraphMailClient(
            http_client=http_client,
            token_provider=TokenProvider(),
            sleep=record_sleep,
        )
        await client.fetch_delta_page(account_id=uuid4(), folder_id="inbox", cursor=None)

    assert delays == [3.0, 2.0]


@pytest.mark.asyncio
async def test_rejects_non_graph_delta_cursor_before_network_access() -> None:
    async with httpx.AsyncClient() as http_client:
        client = GraphMailClient(http_client=http_client, token_provider=TokenProvider())
        with pytest.raises(DeltaStateInvalidError):
            await client.fetch_delta_page(
                account_id=uuid4(),
                folder_id="inbox",
                cursor="https://attacker.example/steal",
            )


@pytest.mark.asyncio
@respx.mock
async def test_throttling_stops_at_the_configured_retry_limit() -> None:
    endpoint = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta"
    route = respx.get(endpoint).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )

    async def no_wait(delay: float) -> None:
        del delay

    async with httpx.AsyncClient() as http_client:
        client = GraphMailClient(
            http_client=http_client,
            token_provider=TokenProvider(),
            max_attempts=3,
            sleep=no_wait,
        )
        with pytest.raises(GraphRateLimitedError):
            await client.fetch_delta_page(account_id=uuid4(), folder_id="inbox", cursor=None)

    assert route.call_count == 3
