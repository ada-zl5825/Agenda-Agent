"""MSAL authorization-code flow backed by encrypted PostgreSQL state."""

import asyncio
import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import msal
from msal import SerializableTokenCache

from recruitment_agent.application.errors import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
)
from recruitment_agent.config.settings import MicrosoftSettings
from recruitment_agent.domain.ports import Clock
from recruitment_agent.microsoft.auth_contracts import (
    AuthorizationCompletion,
    AuthorizationPurpose,
    AuthorizationStart,
    JsonObject,
    MicrosoftAuthStore,
    MsalClient,
    MsalClientFactory,
    StoredAuthorizationFlow,
    TokenCacheSnapshot,
)
from recruitment_agent.microsoft.crypto import AesGcmCipher
from recruitment_agent.microsoft.scopes import GRAPH_DELEGATED_SCOPES

ADMIN_LOGIN_SCOPES: tuple[str, ...] = ("User.Read",)


class DefaultMsalClientFactory:
    """Create confidential MSAL clients without exposing MSAL outside this adapter."""

    def __init__(self, settings: MicrosoftSettings) -> None:
        self._client_id = settings.microsoft_client_id
        self._client_secret = settings.microsoft_client_secret.get_secret_value()
        self._authority = settings.authority

    def create(self, cache: SerializableTokenCache) -> MsalClient:
        client = msal.ConfidentialClientApplication(
            client_id=self._client_id,
            client_credential=self._client_secret,
            authority=self._authority,
            token_cache=cache,
        )
        return cast(MsalClient, client)


class MicrosoftAuthorizationService:
    """Coordinate delegated OAuth while persisting only encrypted MSAL state."""

    _FLOW_TTL = timedelta(minutes=10)

    def __init__(
        self,
        *,
        settings: MicrosoftSettings,
        store: MicrosoftAuthStore,
        cipher: AesGcmCipher,
        clock: Clock,
        client_factory: MsalClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._cipher = cipher
        self._clock = clock
        self._client_factory = client_factory or DefaultMsalClientFactory(settings)

    async def start_admin_authorization(self) -> AuthorizationStart:
        """Authenticate an allowlisted administrator without replacing Graph tokens."""
        return await self._start_authorization(
            scopes=ADMIN_LOGIN_SCOPES,
            purpose=AuthorizationPurpose.ADMIN_LOGIN,
            initiated_by=None,
        )

    async def start_mailbox_authorization(
        self,
        *,
        initiated_by: str,
    ) -> AuthorizationStart:
        """Start an explicit administrator-bound Outlook connection change."""
        normalized_initiator = initiated_by.strip()
        if not normalized_initiator or len(normalized_initiator) > 255:
            raise AuthenticationFailedError("mailbox authorization requires an administrator")
        return await self._start_authorization(
            scopes=GRAPH_DELEGATED_SCOPES,
            purpose=AuthorizationPurpose.MAILBOX_CONNECTION,
            initiated_by=normalized_initiator,
        )

    async def _start_authorization(
        self,
        *,
        scopes: tuple[str, ...],
        purpose: AuthorizationPurpose,
        initiated_by: str | None,
    ) -> AuthorizationStart:
        connection_id = self._settings.microsoft_connection_id
        await self._store.ensure_connection(connection_id)
        # Interactive authorization must not reuse the persisted MSAL cache. Reusing it
        # can make MSAL select the previously authorized account during an account switch.
        cache = SerializableTokenCache()
        client = self._client_factory.create(cache)
        state = secrets.token_urlsafe(32)
        flow = await asyncio.to_thread(
            client.initiate_auth_code_flow,
            scopes,
            redirect_uri=str(self._settings.microsoft_redirect_uri),
            state=state,
            prompt="select_account",
        )
        authorization_url = flow.get("auth_uri")
        if not isinstance(authorization_url, str) or not authorization_url:
            raise AuthenticationFailedError("MSAL did not produce an authorization URL")

        state_hash = self._hash_state(state)
        envelope: JsonObject = {
            "version": 1,
            "purpose": purpose.value,
            "initiated_by": initiated_by,
            "flow": flow,
        }
        encrypted_flow = self._cipher.encrypt(
            json.dumps(envelope, separators=(",", ":")).encode("utf-8"),
            context=self._flow_context(state_hash),
        )
        expires_at = self._clock.now() + self._FLOW_TTL
        await self._store.save_authorization_flow(
            StoredAuthorizationFlow(
                connection_id=connection_id,
                state_hash=state_hash,
                encrypted_flow=encrypted_flow,
                expires_at=expires_at,
            )
        )
        return AuthorizationStart(
            authorization_url=authorization_url,
            expires_at=expires_at,
        )

    async def complete_authorization(
        self,
        auth_response: Mapping[str, str],
        *,
        admin_home_account_id: str | None = None,
    ) -> AuthorizationCompletion:
        state = auth_response.get("state")
        if state is None or not state:
            raise AuthenticationFailedError("OAuth response is missing state")

        state_hash = self._hash_state(state)
        stored_flow = await self._store.consume_authorization_flow(
            state_hash=state_hash,
            consumed_at=self._clock.now(),
        )
        serialized_flow = self._cipher.decrypt(
            stored_flow.encrypted_flow,
            context=self._flow_context(state_hash),
        )
        purpose, initiated_by, flow = self._read_flow_envelope(serialized_flow)
        if purpose is AuthorizationPurpose.MAILBOX_CONNECTION and (
            initiated_by is None
            or admin_home_account_id is None
            or not hmac.compare_digest(initiated_by, admin_home_account_id)
        ):
            raise AuthenticationFailedError(
                "mailbox authorization is not bound to this administrator session"
            )

        # Every interactive exchange uses a fresh cache. Admin login discards it;
        # explicit mailbox connection atomically replaces the persisted Graph cache.
        cache = SerializableTokenCache()
        client = self._client_factory.create(cache)
        try:
            result = await asyncio.to_thread(
                client.acquire_token_by_auth_code_flow,
                flow,
                dict(auth_response),
            )
        except ValueError as exc:
            raise AuthenticationFailedError("OAuth state validation failed") from exc

        if not isinstance(result.get("access_token"), str):
            raise AuthenticationFailedError(self._safe_msal_error(result))

        accounts = await asyncio.to_thread(client.get_accounts)
        account = self._select_interactive_account(accounts)
        home_account_id = account.get("home_account_id")
        if not isinstance(home_account_id, str) or not home_account_id:
            raise AuthenticationFailedError("MSAL account identifier is unavailable")

        tenant_id = self._tenant_id_from_result(result)
        if purpose is AuthorizationPurpose.ADMIN_LOGIN:
            if not await self._is_admin_identity_allowed(
                home_account_id=home_account_id,
                tenant_id=tenant_id,
            ):
                raise AuthenticationFailedError("Microsoft administrator is not authorized")
        else:
            snapshot = await self._load_snapshot(stored_flow.connection_id)
            await self._save_cache(
                snapshot=snapshot,
                cache=cache,
                home_account_id=home_account_id,
                tenant_id=tenant_id,
            )
        return AuthorizationCompletion(
            connection_id=stored_flow.connection_id,
            home_account_id=home_account_id,
            tenant_id=tenant_id,
            purpose=purpose,
        )

    async def _is_admin_identity_allowed(
        self,
        *,
        home_account_id: str,
        tenant_id: str | None,
    ) -> bool:
        configured = self._settings.admin_microsoft_home_account_id
        if configured is not None:
            return hmac.compare_digest(configured, home_account_id)
        return await self._store.is_admin_identity_allowed(
            home_account_id=home_account_id,
            tenant_id=tenant_id,
        )

    async def get_access_token(
        self,
        *,
        connection_id: UUID,
        force_refresh: bool = False,
    ) -> str:
        snapshot, cache = await self._load_cache(connection_id)
        client = self._client_factory.create(cache)
        accounts = await asyncio.to_thread(client.get_accounts)
        if not accounts:
            raise AuthenticationRequiredError("Microsoft account authorization is required")
        account = self._select_account(accounts, snapshot.home_account_id)
        result = await asyncio.to_thread(
            client.acquire_token_silent_with_error,
            GRAPH_DELEGATED_SCOPES,
            account,
            force_refresh=force_refresh,
        )
        await self._save_cache_if_changed(snapshot=snapshot, cache=cache)
        if result is None:
            raise AuthenticationRequiredError("Microsoft account authorization is required")
        access_token = result.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            error = result.get("error")
            if error in {"invalid_grant", "interaction_required", "no_tokens_found"}:
                raise AuthenticationRequiredError("Microsoft account authorization is required")
            raise AuthenticationFailedError(self._safe_msal_error(result))
        return access_token

    async def _load_cache(
        self,
        connection_id: UUID,
    ) -> tuple[TokenCacheSnapshot, SerializableTokenCache]:
        snapshot = await self._load_snapshot(connection_id)
        cache = SerializableTokenCache()
        if snapshot.encrypted_cache is not None:
            serialized = self._cipher.decrypt(
                snapshot.encrypted_cache,
                context=self._cache_context(connection_id),
            )
            try:
                cache.deserialize(serialized.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise AuthenticationFailedError("serialized token cache is invalid") from exc
        return snapshot, cache

    async def _load_snapshot(self, connection_id: UUID) -> TokenCacheSnapshot:
        await self._store.ensure_connection(connection_id)
        return await self._store.load_token_cache(connection_id)

    async def _save_cache_if_changed(
        self,
        *,
        snapshot: TokenCacheSnapshot,
        cache: SerializableTokenCache,
    ) -> None:
        if cache.has_state_changed:
            await self._save_cache(
                snapshot=snapshot,
                cache=cache,
                home_account_id=snapshot.home_account_id,
                tenant_id=snapshot.tenant_id,
            )

    async def _save_cache(
        self,
        *,
        snapshot: TokenCacheSnapshot,
        cache: SerializableTokenCache,
        home_account_id: str | None,
        tenant_id: str | None,
    ) -> None:
        encrypted = self._cipher.encrypt(
            cache.serialize().encode("utf-8"),
            context=self._cache_context(snapshot.connection_id),
        )
        await self._store.save_token_cache(
            connection_id=snapshot.connection_id,
            encrypted_cache=encrypted,
            expected_revision=snapshot.revision,
            home_account_id=home_account_id,
            tenant_id=tenant_id,
        )

    @staticmethod
    def _select_account(
        accounts: list[JsonObject],
        home_account_id: str | None,
    ) -> JsonObject:
        if home_account_id is not None:
            for account in accounts:
                if account.get("home_account_id") == home_account_id:
                    return account
        if accounts:
            return accounts[0]
        raise AuthenticationRequiredError("Microsoft account authorization is required")

    @staticmethod
    def _select_interactive_account(accounts: list[JsonObject]) -> JsonObject:
        if len(accounts) == 1:
            return accounts[0]
        if not accounts:
            raise AuthenticationFailedError(
                "Microsoft did not return the authorized account"
            )
        raise AuthenticationFailedError(
            "Microsoft returned multiple accounts for a single authorization flow"
        )

    @staticmethod
    def _tenant_id_from_result(result: Mapping[str, Any]) -> str | None:
        claims = result.get("id_token_claims")
        if not isinstance(claims, Mapping):
            return None
        tenant_id = claims.get("tid")
        return tenant_id if isinstance(tenant_id, str) else None

    @staticmethod
    def _read_flow_envelope(
        serialized: bytes,
    ) -> tuple[AuthorizationPurpose, str | None, JsonObject]:
        try:
            payload = json.loads(serialized)
            if not isinstance(payload, dict) or payload.get("version") != 1:
                raise ValueError
            purpose = AuthorizationPurpose(str(payload["purpose"]))
            initiated_by_value = payload.get("initiated_by")
            if initiated_by_value is not None and not isinstance(initiated_by_value, str):
                raise ValueError
            flow_value = payload["flow"]
            if not isinstance(flow_value, dict):
                raise ValueError
            return purpose, initiated_by_value, cast(JsonObject, flow_value)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AuthenticationFailedError("encrypted OAuth flow is invalid") from exc

    @staticmethod
    def _safe_msal_error(result: Mapping[str, Any]) -> str:
        error = result.get("error")
        correlation_id = result.get("correlation_id")
        safe_error = error if isinstance(error, str) else "unknown_error"
        safe_correlation = correlation_id if isinstance(correlation_id, str) else "unavailable"
        return f"MSAL authentication failed: {safe_error}; correlation_id={safe_correlation}"

    @staticmethod
    def _hash_state(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_context(connection_id: UUID) -> str:
        return f"msal-token-cache:{connection_id}"

    @staticmethod
    def _flow_context(state_hash: str) -> str:
        return f"msal-auth-flow:{state_hash}"
