"""Persistence contract for encrypted action links."""

from typing import Protocol
from uuid import UUID

from recruitment_agent.links.models import SecureLink, SecureLinkDraft


class SecureLinkRepository(Protocol):
    async def replace_for_email(
        self,
        *,
        source_email_id: UUID,
        links: tuple[SecureLinkDraft, ...],
    ) -> tuple[SecureLink, ...]: ...

    async def get(self, link_id: UUID) -> SecureLink | None: ...
