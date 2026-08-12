"""Versioned application-encryption key contracts and Key Vault adapter."""

import asyncio
from base64 import b64decode
from binascii import Error as Base64Error
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol

from azure.core.exceptions import AzureError
from azure.keyvault.secrets import KeyVaultSecret

from recruitment_agent.application.errors import LinkEncryptionError


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class VersionedKeyMaterial:
    key: bytes
    version: str

    def __post_init__(self) -> None:
        if len(self.key) != 32:
            raise LinkEncryptionError("link encryption key must be exactly 32 bytes")
        if not self.version.strip():
            raise LinkEncryptionError("link encryption key version is unavailable")

    def __repr__(self) -> str:
        return f"VersionedKeyMaterial(version={self.version!r})"


class LinkKeyProvider(Protocol):
    async def get_current_key(self) -> VersionedKeyMaterial: ...

    async def get_key(self, version: str) -> VersionedKeyMaterial: ...


class KeyVaultSecretClient(Protocol):
    def get_secret(
        self,
        name: str,
        version: str | None = None,
        **kwargs: Any,
    ) -> Awaitable[KeyVaultSecret]: ...


class AzureKeyVaultLinkKeyProvider:
    """Load versioned AES keys using a managed-identity-backed async SecretClient."""

    def __init__(
        self,
        *,
        client: KeyVaultSecretClient,
        secret_name: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not secret_name.strip():
            raise ValueError("secret_name must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._client = client
        self._secret_name = secret_name
        self._timeout_seconds = timeout_seconds

    async def get_current_key(self) -> VersionedKeyMaterial:
        return await self._load(version=None)

    async def get_key(self, version: str) -> VersionedKeyMaterial:
        if not version.strip():
            raise LinkEncryptionError("link encryption key version is unavailable")
        return await self._load(version=version)

    async def _load(self, *, version: str | None) -> VersionedKeyMaterial:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                secret = await self._client.get_secret(self._secret_name, version)
        except (TimeoutError, AzureError) as exc:
            raise LinkEncryptionError("link encryption key could not be loaded") from exc
        value = secret.value
        secret_version = secret.properties.version
        if value is None or secret_version is None:
            raise LinkEncryptionError("link encryption key material is incomplete")
        try:
            key = b64decode(value, validate=True)
        except (Base64Error, ValueError) as exc:
            raise LinkEncryptionError("link encryption key is not valid base64") from exc
        return VersionedKeyMaterial(key=key, version=secret_version)


class StaticLinkKeyProvider:
    """In-memory provider for local composition and deterministic tests."""

    def __init__(self, *, current_version: str, keys: dict[str, bytes]) -> None:
        self._current_version = current_version
        self._keys = dict(keys)

    async def get_current_key(self) -> VersionedKeyMaterial:
        return await self.get_key(self._current_version)

    async def get_key(self, version: str) -> VersionedKeyMaterial:
        key = self._keys.get(version)
        if key is None:
            raise LinkEncryptionError("link encryption key version is unavailable")
        return VersionedKeyMaterial(key=key, version=version)
