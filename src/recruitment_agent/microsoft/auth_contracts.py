"""Persistence and MSAL contracts for stateless delegated authentication."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from msal import SerializableTokenCache

from recruitment_agent.microsoft.crypto import EncryptedPayload

JsonObject = dict[str, Any]


class AuthorizationPurpose(StrEnum):
    ADMIN_LOGIN = "admin_login"
    MAILBOX_CONNECTION = "mailbox_connection"


@dataclass(frozen=True, slots=True, kw_only=True)
class TokenCacheSnapshot:
    connection_id: UUID
    revision: int
    encrypted_cache: EncryptedPayload | None
    home_account_id: str | None
    tenant_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredAuthorizationFlow:
    connection_id: UUID
    state_hash: str
    encrypted_flow: EncryptedPayload
    expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationStart:
    authorization_url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationCompletion:
    connection_id: UUID
    home_account_id: str
    tenant_id: str | None
    purpose: AuthorizationPurpose


class MicrosoftAuthStore(Protocol):
    async def ensure_connection(self, connection_id: UUID) -> None: ...

    async def load_token_cache(self, connection_id: UUID) -> TokenCacheSnapshot: ...

    async def save_token_cache(
        self,
        *,
        connection_id: UUID,
        encrypted_cache: EncryptedPayload,
        expected_revision: int,
        home_account_id: str | None,
        tenant_id: str | None,
    ) -> int: ...

    async def save_authorization_flow(self, flow: StoredAuthorizationFlow) -> None: ...

    async def consume_authorization_flow(
        self,
        *,
        state_hash: str,
        consumed_at: datetime,
    ) -> StoredAuthorizationFlow: ...

    async def is_admin_identity_allowed(
        self,
        *,
        home_account_id: str,
        tenant_id: str | None,
    ) -> bool: ...


class MsalClient(Protocol):
    def initiate_auth_code_flow(
        self,
        scopes: Sequence[str],
        redirect_uri: str | None = None,
        state: str | None = None,
        **kwargs: Any,
    ) -> JsonObject: ...

    def acquire_token_by_auth_code_flow(
        self,
        auth_code_flow: Mapping[str, Any],
        auth_response: Mapping[str, str],
        **kwargs: Any,
    ) -> JsonObject: ...

    def acquire_token_silent_with_error(
        self,
        scopes: Sequence[str],
        account: Mapping[str, Any],
        *,
        force_refresh: bool = False,
        **kwargs: Any,
    ) -> JsonObject | None: ...

    def get_accounts(self, username: str | None = None) -> list[JsonObject]: ...


class MsalClientFactory(Protocol):
    def create(self, cache: SerializableTokenCache) -> MsalClient: ...


class AccessTokenProvider(Protocol):
    async def get_access_token(
        self,
        *,
        connection_id: UUID,
        force_refresh: bool = False,
    ) -> str: ...
