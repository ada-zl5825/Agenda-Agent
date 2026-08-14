"""Microsoft Graph Daily Brief sender with duplicate-safe retry boundaries."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from uuid import UUID

import httpx

from recruitment_agent.application.errors import (
    AuthenticationFailedError,
    BriefSendError,
    BriefSendUncertainError,
)
from recruitment_agent.briefs.renderer import RenderedBrief
from recruitment_agent.microsoft.auth_contracts import AccessTokenProvider

Sleep = Callable[[float], Awaitable[None]]


class GraphBriefMailClient:
    """Send one HTML brief; never sends attachments or recruitment source bodies."""

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
        self._http_client = http_client
        self._token_provider = token_provider
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts
        self._max_retry_delay = max_retry_delay_seconds
        self._sleep = sleep

    async def send_brief(
        self,
        *,
        account_id: UUID,
        recipient: str,
        brief: RenderedBrief,
    ) -> None:
        endpoint = f"{self._base_url}/me/sendMail"
        force_refresh = False
        refreshed = False
        for attempt in range(self._max_attempts):
            token = await self._token_provider.get_access_token(
                connection_id=account_id,
                force_refresh=force_refresh,
            )
            try:
                response = await self._http_client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json={
                        "message": {
                            "subject": brief.subject,
                            "body": {"contentType": "HTML", "content": brief.html},
                            "toRecipients": [
                                {"emailAddress": {"address": recipient}}
                            ],
                        },
                        "saveToSentItems": True,
                    },
                )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                # The connection was never established, so the request was
                # definitely not delivered; retrying cannot duplicate mail.
                if attempt + 1 >= self._max_attempts:
                    raise BriefSendError(
                        "Graph sendMail could not connect to the service"
                    ) from exc
                await self._sleep(min(2.0**attempt, self._max_retry_delay))
                continue
            except httpx.RequestError as exc:
                raise BriefSendUncertainError(
                    "Graph sendMail transport outcome is uncertain"
                ) from exc
            if response.status_code == httpx.codes.ACCEPTED:
                return
            if response.status_code == httpx.codes.UNAUTHORIZED:
                if refreshed or attempt + 1 >= self._max_attempts:
                    raise AuthenticationFailedError(
                        "Graph rejected the delegated access token"
                    )
                force_refresh = True
                refreshed = True
                continue
            force_refresh = False
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                if attempt + 1 >= self._max_attempts:
                    raise BriefSendError("Graph sendMail throttling limit was reached")
                await self._sleep(self._retry_delay(attempt, response))
                continue
            if response.status_code >= 500:
                raise BriefSendUncertainError(
                    "Graph sendMail server outcome is uncertain"
                )
            raise BriefSendError(
                f"Graph sendMail was rejected with status {response.status_code}"
            )
        raise BriefSendError("Graph sendMail retry limit was reached")

    def _retry_delay(self, attempt: int, response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return min(2.0**attempt, self._max_retry_delay)
        try:
            delay = float(raw)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
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
