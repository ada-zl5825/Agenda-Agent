"""Idempotent PostgreSQL repository for encrypted action links."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.links.models import (
    ActionLinkType,
    EncryptedActionUrl,
    SecureLink,
    SecureLinkDraft,
)
from recruitment_agent.persistence.models import SecureLinkModel


class SqlAlchemySecureLinkRepository:
    """Replace one email's link set atomically while preserving stable row identity."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def replace_for_email(
        self,
        *,
        source_email_id: UUID,
        links: tuple[SecureLinkDraft, ...],
    ) -> tuple[SecureLink, ...]:
        if any(link.source_email_id != source_email_id for link in links):
            raise ValueError("secure-link source email IDs must match")
        refs = tuple(link.ref for link in links)
        if len(set(refs)) != len(refs):
            raise ValueError("secure-link refs must be unique per email")

        stored_by_ref: dict[str, SecureLink] = {}
        async with self._session_factory.begin() as session:
            stale = delete(SecureLinkModel).where(
                SecureLinkModel.source_email_id == source_email_id
            )
            if refs:
                stale = stale.where(SecureLinkModel.ref.not_in(refs))
            await session.execute(stale)

            for link in links:
                statement = insert(SecureLinkModel).values(
                    source_email_id=source_email_id,
                    ref=link.ref,
                    link_type=link.link_type.value,
                    domain=link.domain,
                    encrypted_url=link.encrypted_url.ciphertext,
                    nonce=link.encrypted_url.nonce,
                    encryption_key_version=link.encrypted_url.key_version,
                    display_text=link.display_text,
                )
                excluded = statement.excluded
                model = await session.scalar(
                    statement.on_conflict_do_update(
                        index_elements=["source_email_id", "ref"],
                        set_={
                            "link_type": excluded.link_type,
                            "domain": excluded.domain,
                            "encrypted_url": excluded.encrypted_url,
                            "nonce": excluded.nonce,
                            "encryption_key_version": excluded.encryption_key_version,
                            "display_text": excluded.display_text,
                            "updated_at": func.now(),
                        },
                    ).returning(SecureLinkModel)
                )
                if model is None:
                    raise RuntimeError("secure link could not be persisted")
                stored_by_ref[model.ref] = self._to_entity(model)
        return tuple(stored_by_ref[ref] for ref in refs)

    async def get(self, link_id: UUID) -> SecureLink | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(SecureLinkModel).where(SecureLinkModel.id == link_id)
            )
        return None if model is None else self._to_entity(model)

    @staticmethod
    def _to_entity(model: SecureLinkModel) -> SecureLink:
        return SecureLink(
            id=model.id,
            source_email_id=model.source_email_id,
            ref=model.ref,
            link_type=ActionLinkType(model.link_type),
            domain=model.domain,
            encrypted_url=EncryptedActionUrl(
                ciphertext=model.encrypted_url,
                nonce=model.nonce,
                key_version=model.encryption_key_version,
            ),
            display_text=model.display_text,
            created_at=model.created_at,
        )
