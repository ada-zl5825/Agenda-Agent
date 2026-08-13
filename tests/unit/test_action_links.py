import asyncio
from base64 import b64encode
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from recruitment_agent.application.errors import LinkEncryptionError, LinkExtractionError
from recruitment_agent.links.classifier import ActionLinkClassifier
from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.links.extractor import ActionLinkExtractor
from recruitment_agent.links.key_provider import (
    AzureKeyVaultLinkKeyProvider,
    StaticLinkKeyProvider,
)
from recruitment_agent.links.models import (
    ActionLinkType,
    EncryptedActionUrl,
    SecureLink,
)
from recruitment_agent.privacy.models import DiscoveredUrl, UrlSource


def discovered(url: str, *, display_text: str | None = None) -> DiscoveredUrl:
    domain = url.split("/", maxsplit=3)[2] if "://" in url else "invalid.example"
    return DiscoveredUrl(
        ordinal=1,
        url=SecretStr(url),
        domain=domain,
        display_text=display_text,
        source=UrlSource.HTML_LINK,
    )


@pytest.mark.parametrize(
    ("url", "display_text", "expected"),
    [
        (
            "https://assessment.example.test/start?candidate=fake&token=fake",
            "Start assessment",
            ActionLinkType.ASSESSMENT,
        ),
        ("https://tenant.zoom.us/j/fake", "Join", ActionLinkType.MEETING),
        ("https://example.test/interview/room", "Interview", ActionLinkType.INTERVIEW),
        ("https://calendly.com/example/slot", "Book a time", ActionLinkType.SCHEDULING),
        ("https://example.test/rsvp", "Confirm attendance", ActionLinkType.CONFIRMATION),
        ("https://example.test/offer/view", "View offer", ActionLinkType.OFFER),
        (
            "https://jobs.example.test/application/status",
            "Candidate portal",
            ActionLinkType.APPLICATION_PORTAL,
        ),
        ("https://example.test/info", "Read details", ActionLinkType.GENERAL),
    ],
)
def test_classifies_supported_action_link_types(
    url: str,
    display_text: str,
    expected: ActionLinkType,
) -> None:
    result = ActionLinkClassifier().classify(discovered(url, display_text=display_text))

    assert result is expected


def test_classifier_rejects_unsupported_scheme() -> None:
    with pytest.raises(LinkExtractionError):
        ActionLinkClassifier().classify(discovered("javascript:alert(1)"))


def test_classifier_does_not_use_secret_query_values() -> None:
    result = ActionLinkClassifier().classify(
        discovered("https://example.test/open?token=assessment")
    )

    assert result is ActionLinkType.GENERAL


def test_extractor_assigns_stable_refs_and_sanitizes_display_metadata() -> None:
    links = (
        discovered(
            "https://assessment.example.test/start?token=fake-token",
            display_text="Open for candidate@example.test",
        ),
        DiscoveredUrl(
            ordinal=2,
            url=SecretStr("https://tenant.zoom.us/j/fake"),
            domain="tenant.zoom.us",
            display_text="Join interview",
            source=UrlSource.HTML_LINK,
        ),
    )

    candidates = ActionLinkExtractor().extract(links)

    assert [candidate.ref for candidate in candidates] == ["ACTION_LINK_01", "ACTION_LINK_02"]
    assert candidates[0].display_text == "Open for [EMAIL_REDACTED]"
    assert "fake-token" not in repr(candidates[0])


def test_extractor_derives_domain_from_destination_instead_of_untrusted_metadata() -> None:
    link = DiscoveredUrl(
        ordinal=1,
        url=SecretStr("https://assessment.example.test/start"),
        domain="spoofed.example",
        display_text="Start assessment",
        source=UrlSource.HTML_LINK,
    )

    candidate = ActionLinkExtractor().extract((link,))[0]

    assert candidate.domain == "assessment.example.test"


@pytest.mark.asyncio
async def test_aes_gcm_round_trip_uses_context_and_hides_plaintext() -> None:
    source_email_id = uuid4()
    raw_url = "https://assessment.example.test/start?token=fake-secret"
    encryptor = ActionLinkEncryptor(
        StaticLinkKeyProvider(current_version="v1", keys={"v1": b"k" * 32})
    )
    encrypted = await encryptor.encrypt(
        source_email_id=source_email_id,
        ref="ACTION_LINK_01",
        destination=SecretStr(raw_url),
    )
    link = SecureLink(
        id=uuid4(),
        source_email_id=source_email_id,
        ref="ACTION_LINK_01",
        link_type=ActionLinkType.ASSESSMENT,
        domain="assessment.example.test",
        encrypted_url=encrypted,
        display_text="Start assessment",
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    resolved = await encryptor.resolve(link)

    assert raw_url.encode() not in encrypted.ciphertext
    assert raw_url not in repr(encrypted)
    assert raw_url not in repr(resolved)
    assert resolved.destination.get_secret_value() == raw_url

    swapped_context = SecureLink(
        id=link.id,
        source_email_id=source_email_id,
        ref="ACTION_LINK_02",
        link_type=link.link_type,
        domain=link.domain,
        encrypted_url=encrypted,
        display_text=link.display_text,
        created_at=link.created_at,
    )
    with pytest.raises(LinkEncryptionError):
        await encryptor.resolve(swapped_context)


@pytest.mark.asyncio
async def test_resolver_rejects_domain_metadata_mismatch() -> None:
    source_email_id = uuid4()
    encryptor = ActionLinkEncryptor(
        StaticLinkKeyProvider(current_version="v1", keys={"v1": b"k" * 32})
    )
    encrypted = await encryptor.encrypt(
        source_email_id=source_email_id,
        ref="ACTION_LINK_01",
        destination=SecretStr("https://assessment.example.test/start"),
    )
    link = SecureLink(
        id=uuid4(),
        source_email_id=source_email_id,
        ref="ACTION_LINK_01",
        link_type=ActionLinkType.ASSESSMENT,
        domain="attacker.example",
        encrypted_url=encrypted,
        display_text=None,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    with pytest.raises(LinkEncryptionError):
        await encryptor.resolve(link)


class FakeSecretClient:
    def __init__(self, value: str, version: str) -> None:
        self.value = value
        self.version = version
        self.requests: list[tuple[str, str | None]] = []

    async def get_secret(
        self,
        name: str,
        version: str | None = None,
        **kwargs: object,
    ) -> object:
        del kwargs
        self.requests.append((name, version))
        return SimpleNamespace(
            value=self.value,
            properties=SimpleNamespace(version=self.version),
        )


@pytest.mark.asyncio
async def test_key_vault_provider_decodes_versioned_key_without_exposing_it() -> None:
    client = FakeSecretClient(b64encode(b"k" * 32).decode(), "secret-version-1")
    provider = AzureKeyVaultLinkKeyProvider(
        client=client,  # type: ignore[arg-type]
        secret_name="link-key",
    )

    current = await provider.get_current_key()
    await provider.get_key("secret-version-1")

    assert current.key == b"k" * 32
    assert current.version == "secret-version-1"
    assert repr(current) == "VersionedKeyMaterial(version='secret-version-1')"
    assert client.requests == [("link-key", None), ("link-key", "secret-version-1")]


class SlowSecretClient(FakeSecretClient):
    async def get_secret(
        self,
        name: str,
        version: str | None = None,
        **kwargs: object,
    ) -> object:
        await asyncio.sleep(0.02)
        return await super().get_secret(name, version, **kwargs)


@pytest.mark.asyncio
async def test_key_vault_provider_has_an_explicit_timeout() -> None:
    client = SlowSecretClient(b64encode(b"k" * 32).decode(), "v1")
    provider = AzureKeyVaultLinkKeyProvider(
        client=client,  # type: ignore[arg-type]
        secret_name="link-key",
        timeout_seconds=0.001,
    )

    with pytest.raises(LinkEncryptionError):
        await provider.get_current_key()


@pytest.mark.asyncio
async def test_encryptor_rejects_userinfo_and_unknown_key_version() -> None:
    provider = StaticLinkKeyProvider(current_version="v1", keys={"v1": b"k" * 32})
    encryptor = ActionLinkEncryptor(provider)

    with pytest.raises(LinkEncryptionError):
        await encryptor.encrypt(
            source_email_id=uuid4(),
            ref="ACTION_LINK_01",
            destination=SecretStr("https://user:password@example.test/path"),
        )

    invalid = SecureLink(
        id=uuid4(),
        source_email_id=uuid4(),
        ref="ACTION_LINK_01",
        link_type=ActionLinkType.GENERAL,
        domain="example.test",
        encrypted_url=EncryptedActionUrl(
            ciphertext=b"ciphertext",
            nonce=b"n" * 12,
            key_version="missing",
        ),
        display_text=None,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    with pytest.raises(LinkEncryptionError):
        await encryptor.resolve(invalid)
