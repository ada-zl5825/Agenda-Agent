from base64 import b64encode
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from msal import SerializableTokenCache

from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.errors import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    TokenCacheConflictError,
)
from recruitment_agent.config.settings import MicrosoftSettings
from recruitment_agent.microsoft.auth import ADMIN_LOGIN_SCOPES, MicrosoftAuthorizationService
from recruitment_agent.microsoft.auth_contracts import (
    AuthorizationPurpose,
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
    def __init__(
        self,
        connection_id: UUID,
        *,
        snapshot: TokenCacheSnapshot | None = None,
    ) -> None:
        self.connection_id = connection_id
        self.flow: StoredAuthorizationFlow | None = None
        self.snapshot = snapshot or TokenCacheSnapshot(
            connection_id=connection_id,
            revision=0,
            encrypted_cache=None,
            home_account_id=None,
            tenant_id=None,
        )
        self.saved_home_account_id: str | None = None
        self.saved_tenant_id: str | None = None
        self.saved_expected_revision: int | None = None
        self.allowed_admin = "new-account"

    async def ensure_connection(self, connection_id: UUID) -> None:
        assert connection_id == self.connection_id

    async def load_token_cache(self, connection_id: UUID) -> TokenCacheSnapshot:
        assert connection_id == self.connection_id
        return self.snapshot

    async def save_token_cache(
        self,
        *,
        connection_id: UUID,
        encrypted_cache: EncryptedPayload,
        expected_revision: int,
        home_account_id: str | None,
        tenant_id: str | None,
    ) -> int:
        assert connection_id == self.connection_id
        del encrypted_cache
        self.saved_home_account_id = home_account_id
        self.saved_tenant_id = tenant_id
        self.saved_expected_revision = expected_revision
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

    async def is_admin_identity_allowed(
        self,
        *,
        home_account_id: str,
        tenant_id: str | None,
    ) -> bool:
        del tenant_id
        return home_account_id == self.allowed_admin


class MsalClient:
    def __init__(self) -> None:
        self.scopes: tuple[str, ...] = ()
        self.prompt: object = None
        self.state: str | None = None

    def initiate_auth_code_flow(
        self,
        scopes: tuple[str, ...],
        redirect_uri: str | None = None,
        state: str | None = None,
        **kwargs: object,
    ) -> JsonObject:
        del redirect_uri
        self.scopes = scopes
        self.prompt = kwargs.get("prompt")
        self.state = state
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
        self.caches: list[SerializableTokenCache] = []

    def create(self, cache: SerializableTokenCache) -> MsalClient:
        self.caches.append(cache)
        return self.client


class ExpiredMsalClient(MsalClient):
    def acquire_token_silent_with_error(self, *args: object, **kwargs: object) -> JsonObject:
        del args, kwargs
        return {"error": "invalid_grant"}

    def get_accounts(self, username: str | None = None) -> list[JsonObject]:
        del username
        return [{"home_account_id": "account-1"}]


class SwitchedAccountMsalClient(MsalClient):
    def acquire_token_by_auth_code_flow(self, *args: object, **kwargs: object) -> JsonObject:
        del args, kwargs
        return {
            "access_token": "new-access-token",
            "id_token_claims": {"tid": "new-tenant"},
        }

    def get_accounts(self, username: str | None = None) -> list[JsonObject]:
        del username
        return [{"home_account_id": "new-account"}]


class AmbiguousAccountMsalClient(SwitchedAccountMsalClient):
    def get_accounts(self, username: str | None = None) -> list[JsonObject]:
        del username
        return [
            {"home_account_id": "old-account"},
            {"home_account_id": "new-account"},
        ]


@pytest.mark.asyncio
async def test_oauth_start_uses_phase_eight_graph_scopes_and_encrypted_flow() -> None:
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

    result = await service.start_mailbox_authorization(initiated_by="admin-account")

    assert result.authorization_url.startswith("https://login.microsoftonline.com")
    assert client.scopes == GRAPH_DELEGATED_SCOPES
    assert client.prompt == "select_account"
    assert "Calendars.ReadWrite" in client.scopes
    assert "Mail.Send" in client.scopes
    assert FORBIDDEN_PHASE_1_SCOPES.isdisjoint(client.scopes)
    assert store.flow is not None
    assert b"login.microsoftonline.com" not in store.flow.encrypted_flow.ciphertext


@pytest.mark.asyncio
async def test_account_switch_replaces_old_cache_with_selected_account() -> None:
    connection_id = uuid4()
    cipher = AesGcmCipher(key=b"k" * 32, key_version="v1")
    old_cache = cipher.encrypt(
        b"old cache must not be deserialized during interactive authorization",
        context=f"msal-token-cache:{connection_id}",
    )
    store = AuthStore(
        connection_id,
        snapshot=TokenCacheSnapshot(
            connection_id=connection_id,
            revision=7,
            encrypted_cache=old_cache,
            home_account_id="old-account",
            tenant_id="old-tenant",
        ),
    )
    client = SwitchedAccountMsalClient()
    factory = Factory(client)
    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=store,
        cipher=cipher,
        clock=SystemClock(),
        client_factory=factory,
    )

    await service.start_mailbox_authorization(initiated_by="admin-account")
    assert client.state is not None
    result = await service.complete_authorization(
        {"state": client.state, "code": "code"},
        admin_home_account_id="admin-account",
    )

    assert result.home_account_id == "new-account"
    assert store.saved_home_account_id == "new-account"
    assert store.saved_tenant_id == "new-tenant"
    assert store.saved_expected_revision == 7
    assert result.purpose is AuthorizationPurpose.MAILBOX_CONNECTION
    assert len(factory.caches) == 2
    assert factory.caches[0] is not factory.caches[1]


@pytest.mark.asyncio
async def test_account_switch_rejects_ambiguous_msal_accounts() -> None:
    connection_id = uuid4()
    client = AmbiguousAccountMsalClient()
    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=AuthStore(connection_id),
        cipher=AesGcmCipher(key=b"k" * 32, key_version="v1"),
        clock=SystemClock(),
        client_factory=Factory(client),
    )

    await service.start_mailbox_authorization(initiated_by="admin-account")
    assert client.state is not None
    with pytest.raises(AuthenticationFailedError, match="multiple accounts"):
        await service.complete_authorization(
            {"state": client.state, "code": "code"},
            admin_home_account_id="admin-account",
        )


@pytest.mark.asyncio
async def test_admin_login_uses_identity_scope_and_does_not_replace_mailbox_cache() -> None:
    connection_id = uuid4()
    store = AuthStore(connection_id)
    client = SwitchedAccountMsalClient()
    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=store,
        cipher=AesGcmCipher(key=b"k" * 32, key_version="v1"),
        clock=SystemClock(),
        client_factory=Factory(client),
    )

    await service.start_admin_authorization()
    assert client.state is not None
    result = await service.complete_authorization({"state": client.state, "code": "code"})

    assert client.scopes == ADMIN_LOGIN_SCOPES
    assert result.purpose is AuthorizationPurpose.ADMIN_LOGIN
    assert store.saved_home_account_id is None


@pytest.mark.asyncio
async def test_admin_login_rejects_an_identity_outside_the_allowlist() -> None:
    connection_id = uuid4()
    store = AuthStore(connection_id)
    store.allowed_admin = "different-account"
    client = SwitchedAccountMsalClient()
    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=store,
        cipher=AesGcmCipher(key=b"k" * 32, key_version="v1"),
        clock=SystemClock(),
        client_factory=Factory(client),
    )

    await service.start_admin_authorization()
    assert client.state is not None
    with pytest.raises(AuthenticationFailedError, match="not authorized"):
        await service.complete_authorization({"state": client.state, "code": "code"})

    assert store.saved_home_account_id is None


@pytest.mark.asyncio
async def test_mailbox_connection_requires_the_initiating_admin_session() -> None:
    connection_id = uuid4()
    client = SwitchedAccountMsalClient()
    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=AuthStore(connection_id),
        cipher=AesGcmCipher(key=b"k" * 32, key_version="v1"),
        clock=SystemClock(),
        client_factory=Factory(client),
    )

    await service.start_mailbox_authorization(initiated_by="admin-account")
    assert client.state is not None
    with pytest.raises(AuthenticationFailedError, match="administrator session"):
        await service.complete_authorization(
            {"state": client.state, "code": "code"},
            admin_home_account_id="different-admin",
        )


def test_aes_gcm_round_trip_and_context_authentication() -> None:
    cipher = AesGcmCipher(key=b"k" * 32, key_version="v1")
    encrypted = cipher.encrypt(b"refresh-token", context="cache:1")

    assert encrypted.ciphertext != b"refresh-token"
    assert len(encrypted.nonce) == 12
    assert cipher.decrypt(encrypted, context="cache:1") == b"refresh-token"

    with pytest.raises(RuntimeError):
        cipher.decrypt(encrypted, context="cache:2")


class StrictScopesMsalClient(MsalClient):
    """Replicates MSAL's runtime assertion that silent-auth scopes must be a list."""

    def acquire_token_silent_with_error(self, *args: object, **kwargs: object) -> JsonObject:
        del kwargs
        scopes = args[0]
        assert isinstance(scopes, list), "Invalid parameter type"
        return {"access_token": "token-1"}

    def get_accounts(self, username: str | None = None) -> list[JsonObject]:
        del username
        return [{"home_account_id": "account-1"}]


@pytest.mark.asyncio
async def test_silent_auth_passes_scopes_as_the_list_msal_requires() -> None:
    connection_id = uuid4()
    client = StrictScopesMsalClient()
    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=AuthStore(connection_id),
        cipher=AesGcmCipher(key=b"k" * 32, key_version="v1"),
        clock=SystemClock(),
        client_factory=Factory(client),
    )

    token = await service.get_access_token(connection_id=connection_id)

    assert token == "token-1"


@pytest.mark.asyncio
async def test_losing_a_concurrent_cache_refresh_still_returns_the_token() -> None:
    """Regression: an optimistic-lock loser holds a valid token; the Graph
    operation must proceed instead of failing with TOKEN_CACHE_CONFLICT."""
    connection_id = uuid4()

    class ConflictStore(AuthStore):
        async def save_token_cache(self, **kwargs: object) -> int:
            del kwargs
            raise TokenCacheConflictError("Microsoft token cache changed concurrently")

    class RefreshedCacheFactory(Factory):
        def create(self, cache: SerializableTokenCache) -> MsalClient:
            cache.has_state_changed = True
            return super().create(cache)

    service = MicrosoftAuthorizationService(
        settings=settings(connection_id),
        store=ConflictStore(connection_id),
        cipher=AesGcmCipher(key=b"k" * 32, key_version="v1"),
        clock=SystemClock(),
        client_factory=RefreshedCacheFactory(StrictScopesMsalClient()),
    )

    token = await service.get_access_token(connection_id=connection_id)

    assert token == "token-1"


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
