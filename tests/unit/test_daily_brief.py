from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from recruitment_agent.application.daily_brief import (
    BriefDispatchStatus,
    DailyBriefService,
)
from recruitment_agent.application.errors import BriefSendUncertainError
from recruitment_agent.briefs.models import BriefItem, BriefSection, DailyBriefSnapshot
from recruitment_agent.briefs.renderer import DailyBriefRenderer, RenderedBrief
from recruitment_agent.jobs.daily_brief import is_daily_brief_delivery_hour
from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.links.key_provider import StaticLinkKeyProvider
from recruitment_agent.links.models import ActionLinkType, SecureLink


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, 7, 30, tzinfo=UTC)


def test_delivery_hour_uses_london_dst_instead_of_utc_cron_time() -> None:
    assert is_daily_brief_delivery_hour(
        now=datetime(2026, 1, 13, 8, tzinfo=UTC),
        timezone="Europe/London",
        local_hour=8,
    )
    assert is_daily_brief_delivery_hour(
        now=datetime(2026, 8, 13, 7, tzinfo=UTC),
        timezone="Europe/London",
        local_hour=8,
    )
    assert not is_daily_brief_delivery_hour(
        now=datetime(2026, 8, 13, 8, tzinfo=UTC),
        timezone="Europe/London",
        local_hour=8,
    )


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
