"""Context-bound AES-256-GCM encryption for secret-bearing action URLs."""

from os import urandom
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from recruitment_agent.application.errors import LinkEncryptionError
from recruitment_agent.links.key_provider import LinkKeyProvider
from recruitment_agent.links.models import EncryptedActionUrl, ResolvedActionLink, SecureLink


class ActionLinkEncryptor:
    _NONCE_LENGTH = 12

    def __init__(self, key_provider: LinkKeyProvider) -> None:
        self._key_provider = key_provider

    async def encrypt(
        self,
        *,
        source_email_id: UUID,
        ref: str,
        destination: SecretStr,
    ) -> EncryptedActionUrl:
        raw_url = destination.get_secret_value()
        self._validate_destination(raw_url)
        material = await self._key_provider.get_current_key()
        nonce = urandom(self._NONCE_LENGTH)
        try:
            ciphertext = AESGCM(material.key).encrypt(
                nonce,
                raw_url.encode("utf-8"),
                self._context(source_email_id=source_email_id, ref=ref),
            )
        except ValueError as exc:
            raise LinkEncryptionError("action link could not be encrypted") from exc
        return EncryptedActionUrl(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=material.version,
        )

    async def resolve(self, link: SecureLink) -> ResolvedActionLink:
        material = await self._key_provider.get_key(link.encrypted_url.key_version)
        try:
            plaintext = AESGCM(material.key).decrypt(
                link.encrypted_url.nonce,
                link.encrypted_url.ciphertext,
                self._context(source_email_id=link.source_email_id, ref=link.ref),
            )
            raw_url = plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise LinkEncryptionError("encrypted action link is invalid") from exc
        parsed_domain = self._validate_destination(raw_url)
        if parsed_domain != link.domain:
            raise LinkEncryptionError("encrypted action link domain does not match metadata")
        return ResolvedActionLink(
            ref=link.ref,
            link_type=link.link_type,
            domain=link.domain,
            destination=SecretStr(raw_url),
        )

    @staticmethod
    def _validate_destination(raw_url: str) -> str:
        parsed = urlsplit(raw_url)
        if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
            raise LinkEncryptionError("action link uses an unsupported URL scheme")
        if parsed.username is not None or parsed.password is not None:
            raise LinkEncryptionError("action link must not contain URL user information")
        return parsed.hostname.lower()

    @staticmethod
    def _context(*, source_email_id: UUID, ref: str) -> bytes:
        return f"secure-action-link:{source_email_id}:{ref}".encode()
