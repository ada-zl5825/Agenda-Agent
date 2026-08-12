"""Application service that encrypts and persists action links idempotently."""

from uuid import UUID

from pydantic import SecretStr

from recruitment_agent.links.encryption import ActionLinkEncryptor
from recruitment_agent.links.extractor import ActionLinkExtractor
from recruitment_agent.links.models import SecuredActionLinks, SecureLinkDraft
from recruitment_agent.links.repository import SecureLinkRepository
from recruitment_agent.privacy.models import DiscoveredUrl


class SecureActionLinkService:
    def __init__(
        self,
        *,
        repository: SecureLinkRepository,
        encryptor: ActionLinkEncryptor,
        extractor: ActionLinkExtractor | None = None,
    ) -> None:
        self._repository = repository
        self._encryptor = encryptor
        self._extractor = extractor or ActionLinkExtractor()

    async def secure(
        self,
        *,
        source_email_id: UUID,
        discovered_urls: tuple[DiscoveredUrl, ...],
        surrounding_text: str,
    ) -> SecuredActionLinks:
        candidates = self._extractor.extract(
            discovered_urls,
            surrounding_text=surrounding_text,
        )
        drafts: list[SecureLinkDraft] = []
        replacements: list[tuple[SecretStr, str]] = []
        for candidate in candidates:
            encrypted = await self._encryptor.encrypt(
                source_email_id=source_email_id,
                ref=candidate.ref,
                destination=candidate.url,
            )
            drafts.append(
                SecureLinkDraft(
                    source_email_id=source_email_id,
                    ref=candidate.ref,
                    link_type=candidate.link_type,
                    domain=candidate.domain,
                    encrypted_url=encrypted,
                    display_text=candidate.display_text,
                )
            )
            replacements.append(
                (
                    candidate.url,
                    self._placeholder(
                        ref=candidate.ref,
                        link_type=candidate.link_type.value,
                        domain=candidate.domain,
                    ),
                )
            )
        stored = await self._repository.replace_for_email(
            source_email_id=source_email_id,
            links=tuple(drafts),
        )
        return SecuredActionLinks(links=stored, replacements=tuple(replacements))

    @staticmethod
    def _placeholder(*, ref: str, link_type: str, domain: str) -> str:
        return f"[{ref}: {link_type} link, domain={domain}]"
