"""Typed Microsoft Graph Calendar adapter with bounded retries."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import ValidationError

from recruitment_agent.application.errors import (
    AuthenticationFailedError,
    CalendarCreateError,
    CalendarEventNotFoundError,
    CalendarUpdateError,
)
from recruitment_agent.calendar.models import CalendarEventDraft, CalendarProviderEvent
from recruitment_agent.microsoft.auth_contracts import AccessTokenProvider
from recruitment_agent.microsoft.graph_models import GraphCalendarEvent

Sleep = Callable[[float], Awaitable[None]]


class GraphCalendarClient:
    """Create and update private, attendee-free events in the user's calendar."""

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
        self._max_attempts = max_attempts
        self._max_retry_delay = max_retry_delay_seconds
        self._sleep = sleep

    async def create_event(
        self,
        *,
        account_id: UUID,
        draft: CalendarEventDraft,
    ) -> CalendarProviderEvent:
        response = await self._request(
            account_id=account_id,
            method="POST",
            endpoint=f"{self._base_url}/me/calendar/events",
            payload=self._payload(draft, include_transaction=True),
            failure_type=CalendarCreateError,
        )
        return self._response_event(response, CalendarCreateError)

    async def update_event(
        self,
        *,
        account_id: UUID,
        event_id: str,
        draft: CalendarEventDraft,
    ) -> CalendarProviderEvent:
        response = await self._request(
            account_id=account_id,
            method="PATCH",
            endpoint=f"{self._base_url}/me/events/{quote(event_id, safe='')}",
            payload=self._payload(draft, include_transaction=False),
            failure_type=CalendarUpdateError,
        )
        return self._response_event(response, CalendarUpdateError)

    async def _request(
        self,
        *,
        account_id: UUID,
        method: str,
        endpoint: str,
        payload: dict[str, object],
        failure_type: type[CalendarCreateError] | type[CalendarUpdateError],
    ) -> httpx.Response:
        force_refresh = False
        refreshed_after_unauthorized = False
        for attempt in range(self._max_attempts):
            token = await self._token_provider.get_access_token(
                connection_id=account_id,
                force_refresh=force_refresh,
            )
            try:
                response = await self._http_client.request(
                    method,
                    endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Prefer": 'IdType="ImmutableId"',
                    },
                )
            except httpx.RequestError as exc:
                if attempt + 1 >= self._max_attempts:
                    raise failure_type("Graph Calendar transport failed") from exc
                await self._sleep(self._retry_delay(attempt, response=None))
                continue

            if response.is_success:
                return response
            if response.status_code == httpx.codes.UNAUTHORIZED:
                if refreshed_after_unauthorized or attempt + 1 >= self._max_attempts:
                    raise AuthenticationFailedError(
                        "Graph rejected the delegated access token"
                    )
                force_refresh = True
                refreshed_after_unauthorized = True
                continue
            force_refresh = False
            if method == "PATCH" and response.status_code == httpx.codes.NOT_FOUND:
                raise CalendarEventNotFoundError("linked Graph Calendar event was not found")
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS or response.status_code >= 500:
                if attempt + 1 >= self._max_attempts:
                    raise failure_type("Graph Calendar transient retry limit was reached")
                await self._sleep(self._retry_delay(attempt, response=response))
                continue
            raise failure_type(
                f"Graph Calendar request failed with status {response.status_code}"
            )
        raise failure_type("Graph Calendar retry limit was reached")

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            raw_retry_after = response.headers.get("Retry-After")
            if raw_retry_after is not None:
                try:
                    delay = float(raw_retry_after)
                except ValueError:
                    try:
                        retry_at = parsedate_to_datetime(raw_retry_after)
                        now = parsedate_to_datetime(response.headers.get("Date", raw_retry_after))
                        delay = max(0.0, (retry_at - now).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        delay = 2.0**attempt
                return min(max(delay, 0.0), self._max_retry_delay)
        return min(2.0**attempt, self._max_retry_delay)

    @staticmethod
    def _payload(
        draft: CalendarEventDraft,
        *,
        include_transaction: bool,
    ) -> dict[str, object]:
        def graph_datetime(value: datetime) -> dict[str, str]:
            aware = value.astimezone(UTC)
            return {
                "dateTime": aware.replace(tzinfo=None).isoformat(timespec="seconds"),
                "timeZone": "UTC",
            }

        payload: dict[str, object] = {
            "subject": draft.subject,
            "body": {"contentType": "text", "content": draft.body},
            "start": graph_datetime(draft.starts_at),
            "end": graph_datetime(draft.ends_at),
            "sensitivity": "private",
            "showAs": "busy",
            "isReminderOn": True,
            "reminderMinutesBeforeStart": 30,
            "attendees": [],
        }
        if include_transaction:
            payload["transactionId"] = draft.transaction_id
        return payload

    @staticmethod
    def _response_event(
        response: httpx.Response,
        failure_type: type[CalendarCreateError] | type[CalendarUpdateError],
    ) -> CalendarProviderEvent:
        try:
            event = GraphCalendarEvent.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise failure_type("Graph returned an invalid Calendar payload") from exc
        return CalendarProviderEvent(event_id=event.id)
