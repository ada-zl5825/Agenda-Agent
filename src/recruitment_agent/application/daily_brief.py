"""Idempotent deterministic Daily Brief generation and delivery."""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from recruitment_agent.application.errors import (
    ApplicationError,
    BriefSendError,
    BriefSendUncertainError,
)
from recruitment_agent.briefs.models import BriefItem, DailyBriefSnapshot
from recruitment_agent.briefs.renderer import DailyBriefRenderer, RenderedBrief
from recruitment_agent.domain.ports import Clock
from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.links.repository import SecureLinkRepository


class BriefDispatchStatus(StrEnum):
    DISPATCHING = "dispatching"
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


#: An in-flight dispatch older than this is considered crashed. It is closed as
#: UNCERTAIN instead of being retried because the Graph send may have happened.
DISPATCH_LEASE = timedelta(minutes=10)

#: Total dispatch claims allowed per local day, counting the first attempt.
MAX_DISPATCH_ATTEMPTS = 3

#: Error code recorded when a crashed in-flight dispatch is closed.
DISPATCH_ABANDONED_ERROR_CODE = "BRIEF_DISPATCH_ABANDONED"


@dataclass(frozen=True, slots=True, kw_only=True)
class DispatchClaimDecision:
    """Deterministic outcome for one claim attempt against the day's audit row."""

    claim: bool
    mark_abandoned: bool = False


def resolve_dispatch_claim(
    *,
    status: BriefDispatchStatus,
    attempt_count: int,
    dispatch_started_at: datetime,
    now: datetime,
) -> DispatchClaimDecision:
    """Decide whether an existing audit row may be claimed again.

    - An active ``dispatching`` row is exclusive: concurrent claims are refused.
    - A ``dispatching`` row older than :data:`DISPATCH_LEASE` belongs to a
      crashed dispatch whose Graph outcome is unknown; it is closed as
      UNCERTAIN and never retried automatically.
    - A ``failed`` row means the mail was definitely not sent, so bounded
      same-day retries are safe.
    - ``accepted`` and ``uncertain`` rows are terminal for the day.
    """
    if status is BriefDispatchStatus.DISPATCHING:
        if now - dispatch_started_at >= DISPATCH_LEASE:
            return DispatchClaimDecision(claim=False, mark_abandoned=True)
        return DispatchClaimDecision(claim=False)
    if status is BriefDispatchStatus.FAILED and attempt_count < MAX_DISPATCH_ATTEMPTS:
        return DispatchClaimDecision(claim=True)
    return DispatchClaimDecision(claim=False)


class DailyBriefStore(Protocol):
    async def load_snapshot(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        timezone: str,
        public_app_base_url: str,
        generated_at: datetime,
    ) -> DailyBriefSnapshot: ...

    async def claim_dispatch(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        timezone: str,
    ) -> bool: ...

    async def mark_accepted(self, *, account_id: UUID, brief_date: date) -> None: ...

    async def mark_failed(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        status: BriefDispatchStatus,
        error_code: str,
    ) -> None: ...


class BriefMailGateway(Protocol):
    async def send_brief(
        self,
        *,
        account_id: UUID,
        recipient: str,
        brief: RenderedBrief,
    ) -> None: ...


class DailyBriefService:
    def __init__(
        self,
        *,
        store: DailyBriefStore,
        secure_links: SecureLinkRepository,
        link_encryptor: ActionLinkEncryptor,
        mail_gateway: BriefMailGateway,
        renderer: DailyBriefRenderer,
        clock: Clock,
        timezone: str,
        public_app_base_url: str,
    ) -> None:
        self._store = store
        self._secure_links = secure_links
        self._link_encryptor = link_encryptor
        self._mail_gateway = mail_gateway
        self._renderer = renderer
        self._clock = clock
        self._timezone = timezone
        self._public_app_base_url = public_app_base_url.rstrip("/")

    async def render_today(self, *, account_id: UUID) -> RenderedBrief:
        return self._renderer.render(await self._load_today(account_id=account_id))

    async def preview_today(self, *, account_id: UUID) -> str:
        return self._renderer.render_console(await self._load_today(account_id=account_id))

    async def _load_today(self, *, account_id: UUID) -> DailyBriefSnapshot:
        now = self._clock.now()
        today = now.astimezone(ZoneInfo(self._timezone)).date()
        return await self._load_resolved_snapshot(
            account_id=account_id,
            brief_date=today,
            generated_at=now,
        )

    async def _render(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        generated_at: datetime,
    ) -> RenderedBrief:
        return self._renderer.render(
            await self._load_resolved_snapshot(
                account_id=account_id,
                brief_date=brief_date,
                generated_at=generated_at,
            )
        )

    async def _load_resolved_snapshot(
        self,
        *,
        account_id: UUID,
        brief_date: date,
        generated_at: datetime,
    ) -> DailyBriefSnapshot:
        snapshot = await self._store.load_snapshot(
            account_id=account_id,
            brief_date=brief_date,
            timezone=self._timezone,
            public_app_base_url=self._public_app_base_url,
            generated_at=generated_at,
        )
        return await self._resolve_action_links(snapshot)

    async def send_today(self, *, account_id: UUID, recipient: str) -> bool:
        now = self._clock.now()
        today = now.astimezone(ZoneInfo(self._timezone)).date()
        claimed = await self._store.claim_dispatch(
            account_id=account_id,
            brief_date=today,
            timezone=self._timezone,
        )
        if not claimed:
            return False
        send_started = False
        try:
            rendered = await self._render(
                account_id=account_id,
                brief_date=today,
                generated_at=now,
            )
            send_started = True
            await self._mail_gateway.send_brief(
                account_id=account_id,
                recipient=recipient,
                brief=rendered,
            )
        except BriefSendUncertainError as exc:
            await self._store.mark_failed(
                account_id=account_id,
                brief_date=today,
                status=BriefDispatchStatus.UNCERTAIN,
                error_code=exc.code,
            )
            raise
        except ApplicationError as exc:
            await self._store.mark_failed(
                account_id=account_id,
                brief_date=today,
                status=BriefDispatchStatus.FAILED,
                error_code=exc.code,
            )
            raise
        except Exception as exc:
            status = (
                BriefDispatchStatus.UNCERTAIN
                if send_started
                else BriefDispatchStatus.FAILED
            )
            await self._store.mark_failed(
                account_id=account_id,
                brief_date=today,
                status=status,
                error_code=(
                    "BRIEF_SEND_UNEXPECTED"
                    if send_started
                    else "BRIEF_GENERATION_FAILED"
                ),
            )
            if send_started:
                raise BriefSendUncertainError(
                    "Daily Brief delivery outcome is uncertain"
                ) from exc
            raise BriefSendError("Daily Brief generation failed") from exc
        await self._store.mark_accepted(account_id=account_id, brief_date=today)
        return True

    async def _resolve_action_links(
        self,
        snapshot: DailyBriefSnapshot,
    ) -> DailyBriefSnapshot:
        items: list[BriefItem] = []
        for item in snapshot.items:
            if item.review_id is not None or item.secure_link_id is None:
                items.append(item)
                continue
            link = await self._secure_links.get(item.secure_link_id)
            if link is None:
                items.append(item)
                continue
            resolved = await self._link_encryptor.resolve(link)
            items.append(replace(item, action_url=resolved.destination))
        return replace(snapshot, items=tuple(items))
