import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from recruitment_agent.application.mail_sync import FetchedMail, MailDeltaPage
from recruitment_agent.application.secure_email_processing import SecureEmailPreparationService
from recruitment_agent.application.secure_links import SecureActionLinkService
from recruitment_agent.domain.mail import SourceEmailCandidate
from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.links.key_provider import StaticLinkKeyProvider
from recruitment_agent.links.models import SecureLink, SecureLinkDraft

FIXTURES = Path(__file__).parents[1] / "fixtures" / "emails"


class MailGateway:
    async def fetch_delta_page(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        cursor: str | None,
    ) -> MailDeltaPage:
        del account_id, folder_id, cursor
        raise AssertionError("not used")

    async def fetch_message(self, *, account_id: UUID, message_id: str) -> FetchedMail:
        del account_id
        return FetchedMail(
            metadata=SourceEmailCandidate(
                graph_message_id=message_id,
                internet_message_id="<secure-link@example.test>",
                subject="Online assessment invitation",
                sender_domain="careers.example",
                received_at=datetime(2026, 8, 12, tzinfo=UTC),
                outlook_web_link=None,
                has_attachments=False,
            ),
            sender_name="Recruiter",
            sender_address="recruiter@careers.example",
            body_content_type="html",
            body_content=(FIXTURES / "tokenized_assessment_link.html").read_text(encoding="utf-8"),
        )


class InMemorySecureLinkRepository:
    def __init__(self) -> None:
        self.links: dict[tuple[UUID, str], SecureLink] = {}

    async def replace_for_email(
        self,
        *,
        source_email_id: UUID,
        links: tuple[SecureLinkDraft, ...],
    ) -> tuple[SecureLink, ...]:
        active_refs = {link.ref for link in links}
        self.links = {
            key: value
            for key, value in self.links.items()
            if key[0] != source_email_id or key[1] in active_refs
        }
        stored: list[SecureLink] = []
        for draft in links:
            key = (source_email_id, draft.ref)
            existing = self.links.get(key)
            entity = SecureLink(
                id=existing.id if existing is not None else uuid4(),
                source_email_id=source_email_id,
                ref=draft.ref,
                link_type=draft.link_type,
                domain=draft.domain,
                encrypted_url=draft.encrypted_url,
                display_text=draft.display_text,
                created_at=(
                    existing.created_at
                    if existing is not None
                    else datetime(2026, 8, 12, tzinfo=UTC)
                ),
            )
            self.links[key] = entity
            stored.append(entity)
        return tuple(stored)

    async def get(self, link_id: UUID) -> SecureLink | None:
        return next((link for link in self.links.values() if link.id == link_id), None)


def service(repository: InMemorySecureLinkRepository) -> SecureEmailPreparationService:
    encryptor = ActionLinkEncryptor(
        StaticLinkKeyProvider(current_version="v1", keys={"v1": b"k" * 32})
    )
    return SecureEmailPreparationService(
        gateway=MailGateway(),
        link_service=SecureActionLinkService(
            repository=repository,
            encryptor=encryptor,
        ),
    )


@pytest.mark.asyncio
async def test_model_ready_text_contains_refs_but_never_plaintext_destinations() -> None:
    repository = InMemorySecureLinkRepository()
    result = await service(repository).prepare(
        account_id=uuid4(),
        source_email_id=uuid4(),
        graph_message_id="graph-1",
    )

    assert len(result.secure_links) == 2
    assert "ACTION_LINK_01" in result.sanitized.text
    assert "ACTION_LINK_02" in result.sanitized.text
    assert "assessment link" in result.sanitized.text
    assert "fake-sensitive-token" not in result.sanitized.text
    assert "fake-session-value" not in result.sanitized.text
    assert "https://" not in result.sanitized.text
    assert "fake-sensitive-token" not in repr(result)
    assert all(link.encrypted_url.ciphertext for link in result.secure_links)
    assert all(
        b"fake-sensitive-token" not in link.encrypted_url.ciphertext for link in result.secure_links
    )


@pytest.mark.asyncio
async def test_repeated_processing_preserves_link_rows_and_refs() -> None:
    repository = InMemorySecureLinkRepository()
    processor = service(repository)
    source_email_id = uuid4()

    first = await processor.prepare(
        account_id=uuid4(),
        source_email_id=source_email_id,
        graph_message_id="graph-1",
    )
    second = await processor.prepare(
        account_id=uuid4(),
        source_email_id=source_email_id,
        graph_message_id="graph-1",
    )

    assert [link.ref for link in first.secure_links] == ["ACTION_LINK_01", "ACTION_LINK_02"]
    assert [link.id for link in second.secure_links] == [link.id for link in first.secure_links]
    assert len(repository.links) == 2


@pytest.mark.asyncio
async def test_safe_representations_do_not_leak_when_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = InMemorySecureLinkRepository()
    result = await service(repository).prepare(
        account_id=uuid4(),
        source_email_id=uuid4(),
        graph_message_id="graph-logged",
    )

    with caplog.at_level(logging.INFO):
        logging.getLogger("phase-three-privacy").info(
            "prepared=%r links=%r",
            result,
            result.secure_links,
        )

    assert "fake-sensitive-token" not in caplog.text
    assert "fake-session-value" not in caplog.text
    assert "https://" not in caplog.text


def test_secure_link_schema_has_no_plaintext_url_column() -> None:
    from recruitment_agent.persistence import models as persistence_models  # noqa: F401
    from recruitment_agent.persistence.base import Base

    columns = set(Base.metadata.tables["app.secure_links"].columns.keys())

    assert {"url", "plaintext_url", "destination_url"}.isdisjoint(columns)
    assert {
        "ref",
        "link_type",
        "domain",
        "encrypted_url",
        "nonce",
        "encryption_key_version",
    } <= columns
