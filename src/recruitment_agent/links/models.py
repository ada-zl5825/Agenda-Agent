"""Provider-neutral secure action-link contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ActionLinkType(StrEnum):
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    MEETING = "meeting"
    CONFIRMATION = "confirmation"
    SCHEDULING = "scheduling"
    APPLICATION_PORTAL = "application_portal"
    OFFER = "offer"
    GENERAL = "general"


class ActionLinkCandidate(BaseModel):
    """Transient classified URL; exact destination is deliberately secret-backed."""

    model_config = ConfigDict(frozen=True)

    ref: str
    url: SecretStr
    link_type: ActionLinkType
    domain: str
    display_text: str | None = Field(default=None, repr=False)


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class EncryptedActionUrl:
    ciphertext: bytes
    nonce: bytes
    key_version: str

    def __repr__(self) -> str:
        return (
            "EncryptedActionUrl("
            f"ciphertext_bytes={len(self.ciphertext)}, "
            f"key_version={self.key_version!r})"
        )


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class SecureLinkDraft:
    source_email_id: UUID
    ref: str
    link_type: ActionLinkType
    domain: str
    encrypted_url: EncryptedActionUrl
    display_text: str | None

    def __repr__(self) -> str:
        return (
            "SecureLinkDraft("
            f"source_email_id={self.source_email_id!r}, "
            f"ref={self.ref!r}, link_type={self.link_type.value!r}, "
            f"domain={self.domain!r})"
        )


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class SecureLink:
    id: UUID
    source_email_id: UUID
    ref: str
    link_type: ActionLinkType
    domain: str
    encrypted_url: EncryptedActionUrl
    display_text: str | None
    created_at: datetime

    def __repr__(self) -> str:
        return (
            "SecureLink("
            f"id={self.id!r}, source_email_id={self.source_email_id!r}, "
            f"ref={self.ref!r}, link_type={self.link_type.value!r}, "
            f"domain={self.domain!r})"
        )


class ResolvedActionLink(BaseModel):
    """Decrypted URL at a trusted rendering boundary; still an untrusted destination."""

    model_config = ConfigDict(frozen=True)

    ref: str
    link_type: ActionLinkType
    domain: str
    destination: SecretStr


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class SecuredActionLinks:
    links: tuple[SecureLink, ...]
    replacements: tuple[tuple[SecretStr, str], ...]

    def plaintext_replacements(self) -> dict[str, str]:
        """Expose raw keys only inside the short-lived normalization call."""
        return {url.get_secret_value(): replacement for url, replacement in self.replacements}

    def __repr__(self) -> str:
        return f"SecuredActionLinks(link_count={len(self.links)})"
