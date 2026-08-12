"""Authenticated encryption for serialized MSAL cache and OAuth flow state."""

from dataclasses import dataclass
from os import urandom

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from recruitment_agent.application.errors import AuthenticationFailedError


@dataclass(frozen=True, slots=True, kw_only=True)
class EncryptedPayload:
    ciphertext: bytes
    nonce: bytes
    key_version: str


class AesGcmCipher:
    """Encrypt sensitive application state with context-bound AES-256-GCM."""

    _NONCE_LENGTH = 12

    def __init__(self, *, key: bytes, key_version: str) -> None:
        if len(key) != 32:
            msg = "AES-GCM key must be exactly 32 bytes"
            raise ValueError(msg)
        if not key_version.strip():
            msg = "key_version must not be empty"
            raise ValueError(msg)
        self._aesgcm = AESGCM(key)
        self._key_version = key_version

    def encrypt(self, plaintext: bytes, *, context: str) -> EncryptedPayload:
        if not context:
            msg = "encryption context must not be empty"
            raise ValueError(msg)
        nonce = urandom(self._NONCE_LENGTH)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, context.encode("utf-8"))
        return EncryptedPayload(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=self._key_version,
        )

    def decrypt(self, payload: EncryptedPayload, *, context: str) -> bytes:
        if payload.key_version != self._key_version:
            raise AuthenticationFailedError("token cache encryption key version is unavailable")
        try:
            return self._aesgcm.decrypt(
                payload.nonce,
                payload.ciphertext,
                context.encode("utf-8"),
            )
        except InvalidTag as exc:
            raise AuthenticationFailedError("encrypted authentication state is invalid") from exc
