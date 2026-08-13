from base64 import b64encode
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.errors import AuthenticationRequiredError
from recruitment_agent.config.settings import MicrosoftSettings
from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService
from recruitment_agent.microsoft.auth_contracts import (
    JsonObject,
    StoredAuthorizationFlow,
    TokenCacheSnapshot,
)
from recruitment_agent.microsoft.crypto import AesGcmCipher, EncryptedPayload
from recruitment_agent.microsoft.scopes import (
    FORBIDDEN_PHASE_1_SCOPES,
    GRAPH_DELEGATED_SCOPES,
)


def settings(connection_id: UUID) -> MicrosoftSettings:
    return MicrosoftSettings(
        microsoft_client_id="client",
        microsoft_client_secret="secret",
        microsoft_redirect_uri="http://localhost:8000/auth/callback",
        microsoft_connection_id=connection_id,
        token_cache_encryption_key=b64encode(b"k" * 32).decode(),
    )


class AuthStore:
    def __init__(self, connection_id: UUID) -> None:
        self.connection_id = connection_id
        self.flow: StoredAuthorizationFlow | None = None

    async def ensure_connection(self, connection_id: UUID) -> None:
        assert connection_id == self.connection_id

    async def load_token_cache(self, connection_id: UUID) -> TokenCacheSnapshot:
        return TokenCacheSnapshot(
            connection_id=connection_id,
            revision=0,
            encrypted_cache=None,
            home_account_id=None,
            tenant_id=None,
        )

    async def save_token_cache(
        self,
        *,
        connection_id: UUID,
        encrypted_cache: EncryptedPayload,
        expected_revision: int,
        home_account_id: str | None,
        tenant_id: str | None,
    ) -> int:
        del connection_id, encrypted_cache, expected_revision, home_account_id, tenant_id
        return 1

    async def save_authorization_flow(self, flow: StoredAuthorizationFlow) -> None:
        self.flow = flow

    async def consume_authorization_flow(
        self,
        *,
        state_hash: str,
        consumed_at: datetime,
    ) -> StoredAuthorizationFlow:
        del state_hash, consumed_at
        assert self.flow is not None
        return self.flow


class MsalClient:
    def __init__(self) -> None:
        self.scopes: tuple[str, ...] = ()

    def initiate_auth_code_flow(
        self,
        scopes: tuple[str, ...],
        redirect_uri: str | None = None,
        state: str | None = None,
        **kwargs: object,
    ) -> JsonObject:
        del redirect_uri, kwargs
        self.scopes = scopes
        return {"auth_uri": "https://login.microsoftonline.com/authorize", "state": state}

    def acquire_token_by_auth_code_flow(self, *args: object, **kwargs: object) -> JsonObject:
        del args, kwargs
        raise AssertionError("not used")

    def acquire_token_silent_with_error(self, *args: object, **kwargs: object) -> JsonObject:
        del args, kwargs
        raise AssertionError("not used")

    def get_accounts(self, username: str | None = None) -> list[JsonObject]:
        del username
        return []


class Factory:
    def __init__(self, client: MsalClient) -> None:
        self.client = client

    def create(self, cache: object) -> MsalClient:
        del cache
        return self.client


class ExpiredMsalClient(MsalClient):
    def acquire_token_silent_with_error(self, *args: object, **kwargs: object) -> JsonObject:
        del args, kwargs
        return {"error": "invalid_grant"}

    def get_accounts(self, username: str | None = None) -> list[JsonObject]:
        del username
        return [{"home_account_id": "account-1"}]


@pytest.mark.asyncio
async def test_oauth_start_uses_phase_seven_graph_scopes_and_encrypted_flow() -> None:
    connection_id = uuid4()
    store = AuthStore(connection_id)
    client = MsalClient()
    cipher = AesGcmCipher(key=b"k" * 32, key_version="v1")
    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=store,
        cipher=cipher,
        clock=SystemClock(),
        client_factory=Factory(client),
    )

    result = await service.start_authorization()

    assert result.authorization_url.startswith("https://login.microsoftonline.com")
    assert client.scopes == GRAPH_DELEGATED_SCOPES
    assert "Calendars.ReadWrite" in client.scopes
    assert FORBIDDEN_PHASE_1_SCOPES.isdisjoint(client.scopes)
    assert store.flow is not None
    assert b"login.microsoftonline.com" not in store.flow.encrypted_flow.ciphertext


def test_aes_gcm_round_trip_and_context_authentication() -> None:
    cipher = AesGcmCipher(key=b"k" * 32, key_version="v1")
    encrypted = cipher.encrypt(b"refresh-token", context="cache:1")

    assert encrypted.ciphertext != b"refresh-token"
    assert len(encrypted.nonce) == 12
    assert cipher.decrypt(encrypted, context="cache:1") == b"refresh-token"

    with pytest.raises(RuntimeError):
        cipher.decrypt(encrypted, context="cache:2")


@pytest.mark.asyncio
async def test_expired_silent_auth_requires_new_user_authorization() -> None:
    connection_id = uuid4()
    client = ExpiredMsalClient()
    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=AuthStore(connection_id),
        cipher=AesGcmCipher(key=b"k" * 32, key_version="v1"),
        clock=SystemClock(),
        client_factory=Factory(client),
    )

    with pytest.raises(AuthenticationRequiredError):
        await service.get_access_token(connection_id=connection_id)
