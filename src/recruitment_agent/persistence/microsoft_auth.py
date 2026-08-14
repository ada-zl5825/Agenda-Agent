"""PostgreSQL persistence for encrypted Microsoft authorization state."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.application.errors import (
    AuthenticationFailedError,
    TokenCacheConflictError,
)
from recruitment_agent.domain.mail import MailSyncStatus
from recruitment_agent.microsoft.auth_contracts import (
    StoredAuthorizationFlow,
    TokenCacheSnapshot,
)
from recruitment_agent.microsoft.crypto import EncryptedPayload
from recruitment_agent.persistence.models import (
    AdminIdentityModel,
    MailSyncStateModel,
    MicrosoftAuthorizationFlowModel,
    MicrosoftConnectionModel,
)


class SqlAlchemyMicrosoftAuthStore:
    """Keep credentials encrypted and use revisions to prevent lost cache updates."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_connection(self, connection_id: UUID) -> None:
        async with self._session_factory.begin() as session:
            statement = insert(MicrosoftConnectionModel).values(id=connection_id)
            await session.execute(statement.on_conflict_do_nothing(index_elements=["id"]))

    async def load_token_cache(self, connection_id: UUID) -> TokenCacheSnapshot:
        async with self._session_factory() as session:
            model = await session.get(MicrosoftConnectionModel, connection_id)
        if model is None:
            raise AuthenticationFailedError("Microsoft connection does not exist")
        encrypted = None
        encrypted_parts = (
            model.token_cache_ciphertext,
            model.token_cache_nonce,
            model.token_cache_key_version,
        )
        if any(part is not None for part in encrypted_parts):
            if not all(part is not None for part in encrypted_parts):
                raise AuthenticationFailedError("encrypted token cache is incomplete")
            encrypted = EncryptedPayload(
                ciphertext=model.token_cache_ciphertext or b"",
                nonce=model.token_cache_nonce or b"",
                key_version=model.token_cache_key_version or "",
            )
        return TokenCacheSnapshot(
            connection_id=model.id,
            revision=model.token_cache_revision,
            encrypted_cache=encrypted,
            home_account_id=model.home_account_id,
            tenant_id=model.tenant_id,
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
        next_revision = expected_revision + 1
        async with self._session_factory.begin() as session:
            model = await session.scalar(
                select(MicrosoftConnectionModel)
                .where(MicrosoftConnectionModel.id == connection_id)
                .with_for_update()
            )
            if model is None or model.token_cache_revision != expected_revision:
                raise TokenCacheConflictError("Microsoft token cache changed concurrently")
            account_changed = (
                model.home_account_id is not None
                and home_account_id is not None
                and model.home_account_id != home_account_id
            )
            model.token_cache_ciphertext = encrypted_cache.ciphertext
            model.token_cache_nonce = encrypted_cache.nonce
            model.token_cache_key_version = encrypted_cache.key_version
            model.token_cache_revision = next_revision
            model.home_account_id = home_account_id
            model.tenant_id = tenant_id
            if account_changed:
                await session.execute(
                    update(MailSyncStateModel)
                    .where(MailSyncStateModel.account_id == connection_id)
                    .values(
                        delta_link=None,
                        last_sync_started_at=None,
                        last_sync_finished_at=None,
                        status=MailSyncStatus.IDLE.value,
                        error_code=None,
                    )
                )
        return next_revision

    async def save_authorization_flow(self, flow: StoredAuthorizationFlow) -> None:
        async with self._session_factory.begin() as session:
            session.add(
                MicrosoftAuthorizationFlowModel(
                    connection_id=flow.connection_id,
                    state_hash=flow.state_hash,
                    flow_ciphertext=flow.encrypted_flow.ciphertext,
                    flow_nonce=flow.encrypted_flow.nonce,
                    key_version=flow.encrypted_flow.key_version,
                    expires_at=flow.expires_at,
                )
            )

    async def consume_authorization_flow(
        self,
        *,
        state_hash: str,
        consumed_at: datetime,
    ) -> StoredAuthorizationFlow:
        async with self._session_factory.begin() as session:
            model = await session.scalar(
                select(MicrosoftAuthorizationFlowModel)
                .where(MicrosoftAuthorizationFlowModel.state_hash == state_hash)
                .with_for_update()
            )
            if model is None or model.used_at is not None or model.expires_at <= consumed_at:
                raise AuthenticationFailedError("OAuth flow is missing, expired, or already used")
            model.used_at = consumed_at
            return StoredAuthorizationFlow(
                connection_id=model.connection_id,
                state_hash=model.state_hash,
                encrypted_flow=EncryptedPayload(
                    ciphertext=model.flow_ciphertext,
                    nonce=model.flow_nonce,
                    key_version=model.key_version,
                ),
                expires_at=model.expires_at,
            )

    async def is_admin_identity_allowed(
        self,
        *,
        home_account_id: str,
        tenant_id: str | None,
    ) -> bool:
        async with self._session_factory() as session:
            model = await session.get(AdminIdentityModel, home_account_id)
        if model is None or not model.enabled:
            return False
        return model.tenant_id is None or model.tenant_id == tenant_id
