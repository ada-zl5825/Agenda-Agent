from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from recruitment_agent.application.daily_brief import (
    MAX_DISPATCH_ATTEMPTS,
    BriefDispatchStatus,
    DailyBriefService,
    resolve_dispatch_claim,
)
from recruitment_agent.application.errors import BriefSendUncertainError
from recruitment_agent.briefs.models import BriefItem, BriefSection, DailyBriefSnapshot
from recruitment_agent.briefs.renderer import DailyBriefRenderer, RenderedBrief
from recruitment_agent.jobs import daily_brief as daily_brief_job
from recruitment_agent.jobs.daily_brief import is_daily_brief_due
from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.links.key_provider import StaticLinkKeyProvider
from recruitment_agent.links.models import ActionLinkType, SecureLink


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, 7, 30, tzinfo=UTC)


def test_delivery_due_uses_london_dst_instead_of_utc_cron_time() -> None:
    assert is_daily_brief_due(
        now=datetime(2026, 1, 13, 8, tzinfo=UTC),
        timezone="Europe/London",
        local_hour=8,
    )
    assert is_daily_brief_due(
        now=datetime(2026, 8, 13, 7, tzinfo=UTC),
        timezone="Europe/London",
        local_hour=8,
    )
    assert not is_daily_brief_due(
        now=datetime(2026, 8, 13, 6, tzinfo=UTC),
        timezone="Europe/London",
        local_hour=8,
    )


def test_late_timer_tick_is_still_due_the_same_local_day() -> None:
    """A cold-started host must not silently skip the whole day's brief."""
    assert is_daily_brief_due(
        now=datetime(2026, 8, 13, 8, 5, tzinfo=UTC),  # 09:05 London
        timezone="Europe/London",
        local_hour=8,
    )
    assert is_daily_brief_due(
        now=datetime(2026, 8, 13, 22, tzinfo=UTC),
        timezone="Europe/London",
        local_hour=8,
    )


def test_dispatch_claim_is_exclusive_while_a_send_is_in_flight() -> None:
    """Regression: a concurrent manual send must not double-send the brief."""
    started = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
    decision = resolve_dispatch_claim(
        status=BriefDispatchStatus.DISPATCHING,
        attempt_count=1,
        dispatch_started_at=started,
        now=started + timedelta(minutes=2),
    )
    assert not decision.claim
    assert not decision.mark_abandoned


def test_stale_dispatch_is_closed_as_uncertain_not_retried() -> None:
    started = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
    decision = resolve_dispatch_claim(
        status=BriefDispatchStatus.DISPATCHING,
        attempt_count=1,
        dispatch_started_at=started,
        now=started + timedelta(minutes=11),
    )
    assert not decision.claim
    assert decision.mark_abandoned


def test_failed_dispatch_allows_bounded_same_day_retries() -> None:
    started = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
    now = started + timedelta(hours=1)
    retry = resolve_dispatch_claim(
        status=BriefDispatchStatus.FAILED,
        attempt_count=1,
        dispatch_started_at=started,
        now=now,
    )
    assert retry.claim
    capped = resolve_dispatch_claim(
        status=BriefDispatchStatus.FAILED,
        attempt_count=MAX_DISPATCH_ATTEMPTS,
        dispatch_started_at=started,
        now=now,
    )
    assert not capped.claim
    assert not capped.mark_abandoned


def test_terminal_dispatch_statuses_are_never_reclaimed() -> None:
    started = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
    now = started + timedelta(hours=2)
    for status in (BriefDispatchStatus.ACCEPTED, BriefDispatchStatus.UNCERTAIN):
        decision = resolve_dispatch_claim(
            status=status,
            attempt_count=1,
            dispatch_started_at=started,
            now=now,
        )
        assert not decision.claim
        assert not decision.mark_abandoned


@pytest.mark.asyncio
async def test_manual_daily_brief_bypasses_timer_hour_but_keeps_service_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = uuid4()
    calls: list[tuple[UUID, str]] = []

    class Settings:
        microsoft_connection_id = account_id

    class Service:
        async def send_today(self, *, account_id: UUID, recipient: str) -> bool:
            calls.append((account_id, recipient))
            return True

    @asynccontextmanager
    async def service_context() -> AsyncIterator[Service]:
        yield Service()

    monkeypatch.setattr(daily_brief_job, "get_microsoft_settings", lambda: Settings())
    monkeypatch.setattr(daily_brief_job, "_daily_brief_service", service_context)

    assert await daily_brief_job.send_daily_brief_now(
        recipient="configured@example.test"
    )
    assert calls == [(account_id, "configured@example.test")]


class Store:
    def __init__(self, snapshot: DailyBriefSnapshot) -> None:
        self.snapshot = snapshot
        self.claimed = False
        self.status: BriefDispatchStatus | None = None
        self.error_code: str | None = None

    async def load_snapshot(self, **_kwargs: object) -> DailyBriefSnapshot:
        return self.snapshot

    async def claim_dispatch(self, **_kwargs: object) -> bool:
        if self.claimed:
            return False
        self.claimed = True
        self.status = BriefDispatchStatus.DISPATCHING
        return True

    async def mark_accepted(self, **_kwargs: object) -> None:
        self.status = BriefDispatchStatus.ACCEPTED

    async def mark_failed(
        self,
        *,
        status: BriefDispatchStatus,
        error_code: str,
        **_kwargs: object,
    ) -> None:
        self.status = status
        self.error_code = error_code


class Links:
    def __init__(self, link: SecureLink) -> None:
        self.link = link
        self.requested: list[UUID] = []

    async def get(self, link_id: UUID) -> SecureLink | None:
        self.requested.append(link_id)
        return self.link if link_id == self.link.id else None

    async def replace_for_email(self, **_kwargs: object) -> tuple[SecureLink, ...]:
        raise AssertionError("Daily Brief must not mutate secure links")


class Mail:
    def __init__(self, *, uncertain: bool = False) -> None:
        self.uncertain = uncertain
        self.sent: list[RenderedBrief] = []

    async def send_brief(self, **kwargs: object) -> None:
        brief = kwargs["brief"]
        assert isinstance(brief, RenderedBrief)
        self.sent.append(brief)
        if self.uncertain:
            raise BriefSendUncertainError("unknown Graph outcome")


async def _fixture(
    *,
    uncertain: bool = False,
) -> tuple[DailyBriefService, Store, Links, Mail, str]:
    source_id = uuid4()
    encryptor = ActionLinkEncryptor(
        StaticLinkKeyProvider(current_version="v1", keys={"v1": b"k" * 32})
    )
    destination = "https://assessment.example.test/start?token=plaintext-secret"
    encrypted = await encryptor.encrypt(
        source_email_id=source_id,
        ref="ACTION_LINK_01",
        destination=SecretStr(destination),
    )
    link = SecureLink(
        id=uuid4(),
        source_email_id=source_id,
        ref="ACTION_LINK_01",
        link_type=ActionLinkType.ASSESSMENT,
        domain="assessment.example.test",
        encrypted_url=encrypted,
        display_text="Start assessment",
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    review_id = uuid4()
    snapshot = DailyBriefSnapshot(
        account_id=uuid4(),
        brief_date=date(2026, 8, 13),
        timezone="Europe/London",
        generated_at=Clock().now(),
        items=(
            BriefItem(
                identity="action:1",
                section=BriefSection.ACTION_REQUIRED,
                company="Example & Co",
                role="Engineer",
                stage="Assessment",
                secure_link_id=link.id,
                action_label="Open action",
            ),
            BriefItem(
                identity="review:1",
                section=BriefSection.NEEDS_REVIEW,
                company="Example",
                role="Engineer",
                stage="TIMEZONE_AMBIGUITY",
                secure_link_id=uuid4(),
                review_id=review_id,
                review_url=f"https://agent.example/reviews/{review_id}",
            ),
        ),
    )
    store = Store(snapshot)
    links = Links(link)
    mail = Mail(uncertain=uncertain)
    service = DailyBriefService(
        store=store,
        secure_links=links,
        link_encryptor=encryptor,
        mail_gateway=mail,
        renderer=DailyBriefRenderer(),
        clock=Clock(),
        timezone="Europe/London",
        public_app_base_url="https://agent.example",
    )
    return service, store, links, mail, destination


@pytest.mark.asyncio
async def test_brief_decrypts_only_ordinary_actions_and_sends_once() -> None:
    service, store, links, mail, destination = await _fixture()

    assert await service.send_today(account_id=store.snapshot.account_id, recipient="me@test")
    assert not await service.send_today(
        account_id=store.snapshot.account_id,
        recipient="me@test",
    )

    assert len(mail.sent) == 1
    assert store.status is BriefDispatchStatus.ACCEPTED
    assert links.requested == [links.link.id]
    assert destination in mail.sent[0].html
    assert "Open Review" in mail.sent[0].html
    assert "Example &amp; Co" in mail.sent[0].html
    assert destination not in repr(mail.sent[0])


@pytest.mark.asyncio
async def test_uncertain_send_is_audited_and_never_reclaimed() -> None:
    service, store, _links, _mail, _destination = await _fixture(uncertain=True)

    with pytest.raises(BriefSendUncertainError):
        await service.send_today(
            account_id=store.snapshot.account_id,
            recipient="me@test",
        )

    assert store.status is BriefDispatchStatus.UNCERTAIN
    assert store.error_code == "BRIEF_SEND_FAILED"
    assert not await service.send_today(
        account_id=store.snapshot.account_id,
        recipient="me@test",
    )


def test_brief_console_preview_uses_console_chrome_and_keeps_email_mail_safe() -> None:
    review_id = uuid4()
    snapshot = DailyBriefSnapshot(
        account_id=uuid4(),
        brief_date=date(2026, 8, 13),
        timezone="Europe/London",
        generated_at=Clock().now(),
        items=(
            BriefItem(
                identity="review:1",
                section=BriefSection.NEEDS_REVIEW,
                company="Example",
                role="Engineer",
                stage="确认时区",
                review_id=review_id,
                review_url=f"https://agent.example/reviews/{review_id}",
            ),
        ),
    )
    renderer = DailyBriefRenderer()
    email = renderer.render(snapshot)
    preview = renderer.render_console(snapshot)

    assert "Agenda Agent" in preview
    assert "今日 Daily Brief" in preview
    assert "待确认" in preview
    assert "打开 Review" in preview
    assert "class=\"topbar\"" in preview
    assert "Recruitment Brief" in email.html
    assert "Open Review" in email.html
    assert "class=\"topbar\"" not in email.html
    assert "Agenda Agent" not in email.html


def test_empty_brief_console_preview_shows_empty_state() -> None:
    snapshot = DailyBriefSnapshot(
        account_id=uuid4(),
        brief_date=date(2026, 8, 13),
        timezone="Europe/London",
        generated_at=Clock().now(),
        items=(),
    )
    html = DailyBriefRenderer().render_console(snapshot)

    assert "今天没有需要关注的招聘事项." in html
    assert "无需处理" in html
