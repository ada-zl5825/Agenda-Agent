"""Read-only, typed Microsoft Graph mail adapter with bounded retries."""

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
from pydantic import ValidationError

from recruitment_agent.application.errors import (
    AuthenticationFailedError,
    DeltaStateInvalidError,
    GraphFetchError,
    GraphRateLimitedError,
)
from recruitment_agent.application.mail_sync import FetchedMail, MailDeltaPage
from recruitment_agent.domain.mail import SourceEmailCandidate
from recruitment_agent.microsoft.auth_contracts import AccessTokenProvider
from recruitment_agent.microsoft.graph_models import GraphDeltaResponse, GraphMessage

Sleep = Callable[[float], Awaitable[None]]

LOGGER = logging.getLogger(__name__)


class GraphMailClient:
    """Access only message metadata/body; attachment APIs are intentionally absent."""

    _DELTA_SELECT = (
        "id,internetMessageId,subject,from,receivedDateTime,webLink,hasAttachments"
    )
    _MESSAGE_SELECT = f"{_DELTA_SELECT},body"

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        token_provider: AccessTokenProvider,
        base_url: str = "https://graph.microsoft.com/v1.0",
        max_attempts: int = 4,
        max_retry_delay_seconds: float = 30.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._http_client = http_client
        self._token_provider = token_provider
        self._base_url = base_url.rstrip("/")
        self._base_host = urlparse(self._base_url).hostname
        self._max_attempts = max_attempts
        self._max_retry_delay = max_retry_delay_seconds
        self._sleep = sleep

    async def fetch_delta_page(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        cursor: str | None,
    ) -> MailDeltaPage:
        if cursor is None:
            endpoint = (
                f"{self._base_url}/me/mailFolders/{quote(folder_id, safe='')}/messages/delta"
            )
            params: dict[str, str] | None = {"$select": self._DELTA_SELECT}
        else:
            endpoint = self._validated_cursor(cursor)
            params = None

        response = await self._request(
            account_id=account_id,
            endpoint=endpoint,
            params=params,
            prefer='odata.maxpagesize=50',
        )
        try:
            payload = GraphDeltaResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise GraphFetchError("Graph returned an invalid mail delta payload") from exc
        messages: list[SourceEmailCandidate] = []
        for message in payload.value:
            if message.removed is not None:
                continue
            try:
                messages.append(self._to_candidate(message))
            except ValueError:
                # One malformed item must not wedge the whole delta stream.
                # Only the opaque Graph identifier is logged; never content.
                LOGGER.warning(
                    "graph_delta_message_skipped",
                    extra={"graph_message_id": message.id},
                )
        return MailDeltaPage(
            messages=tuple(messages),
            next_link=payload.next_link,
            delta_link=payload.delta_link,
        )

    async def fetch_message(self, *, account_id: UUID, message_id: str) -> FetchedMail:
        endpoint = f"{self._base_url}/me/messages/{quote(message_id, safe='')}"
        response = await self._request(
            account_id=account_id,
            endpoint=endpoint,
            params={"$select": self._MESSAGE_SELECT},
            prefer='outlook.body-content-type="html"',
        )
        try:
            message = GraphMessage.model_validate(response.json())
            if message.body is None:
                raise ValueError("message body is absent")
            metadata = self._to_candidate(
                message,
                body_hash=hashlib.sha256(message.body.content.encode("utf-8")).hexdigest(),
            )
        except (ValueError, ValidationError) as exc:
            raise GraphFetchError("Graph returned an invalid message payload") from exc
        return FetchedMail(
            metadata=metadata,
            sender_name=(
                message.sender.email_address.name
                if message.sender is not None and message.sender.email_address is not None
                else None
            ),
            sender_address=(
                message.sender.email_address.address
                if message.sender is not None and message.sender.email_address is not None
                else None
            ),
            body_content_type=message.body.content_type,
            body_content=message.body.content,
        )

    async def _request(
        self,
        *,
        account_id: UUID,
        endpoint: str,
        params: dict[str, str] | None,
        prefer: str,
    ) -> httpx.Response:
        force_refresh = False
        refreshed_after_unauthorized = False
        for attempt in range(self._max_attempts):
            token = await self._token_provider.get_access_token(
                connection_id=account_id,
                force_refresh=force_refresh,
            )
            try:
                response = await self._http_client.get(
                    endpoint,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Prefer": prefer,
                    },
                )
            except httpx.RequestError as exc:
                if attempt + 1 >= self._max_attempts:
                    raise GraphFetchError("Graph request transport failed") from exc
                await self._sleep(self._retry_delay(attempt, response=None))
                continue

            if response.is_success:
                return response
            if response.status_code == httpx.codes.UNAUTHORIZED:
                if refreshed_after_unauthorized or attempt + 1 >= self._max_attempts:
                    raise AuthenticationFailedError("Graph rejected the delegated access token")
                force_refresh = True
                refreshed_after_unauthorized = True
                continue
            force_refresh = False
            if response.status_code == httpx.codes.GONE:
                raise DeltaStateInvalidError("Graph delta cursor is no longer valid")
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                if attempt + 1 >= self._max_attempts:
                    raise GraphRateLimitedError("Graph throttling retry limit was reached")
                await self._sleep(self._retry_delay(attempt, response=response))
                continue
            if response.status_code >= 500:
                if attempt + 1 >= self._max_attempts:
                    raise GraphFetchError("Graph transient retry limit was reached")
                await self._sleep(self._retry_delay(attempt, response=response))
                continue
            raise GraphFetchError(f"Graph request failed with status {response.status_code}")
        raise GraphFetchError("Graph retry limit was reached")

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            raw_retry_after = response.headers.get("Retry-After")
            if raw_retry_after is not None:
                try:
                    delay = float(raw_retry_after)
                except ValueError:
                    try:
                        retry_at = parsedate_to_datetime(raw_retry_after)
                        date_header = response.headers.get("Date")
                        now = (
                            parsedate_to_datetime(date_header)
                            if date_header is not None
                            else datetime.now(UTC)
                        )
                        delay = max(0.0, (retry_at - now).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        delay = 2.0**attempt
                return min(max(delay, 0.0), self._max_retry_delay)
        return min(2.0**attempt, self._max_retry_delay)

    def _validated_cursor(self, cursor: str) -> str:
        parsed = urlparse(cursor)
        if parsed.scheme != "https" or parsed.hostname != self._base_host:
            raise DeltaStateInvalidError("delta cursor does not target the configured Graph host")
        return cursor

    @staticmethod
    def _to_candidate(
        message: GraphMessage,
        *,
        body_hash: str | None = None,
    ) -> SourceEmailCandidate:
        if message.received_at is None:
            raise ValueError("receivedDateTime is absent")
        sender_address = (
            message.sender.email_address.address
            if message.sender is not None and message.sender.email_address is not None
            else None
        )
        sender_domain = None
        if sender_address is not None and "@" in sender_address:
            sender_domain = sender_address.rsplit("@", maxsplit=1)[1].lower()
        return SourceEmailCandidate(
            graph_message_id=message.id,
            internet_message_id=message.internet_message_id,
            subject=message.subject or "",
            sender_domain=sender_domain,
            received_at=message.received_at,
            outlook_web_link=message.web_link,
            has_attachments=message.has_attachments,
            body_hash=body_hash,
        )
