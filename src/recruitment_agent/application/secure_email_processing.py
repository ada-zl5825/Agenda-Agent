"""Phase 3 email preparation with encrypted links and opaque model-safe references."""

from dataclasses import dataclass
from uuid import UUID

from recruitment_agent.application.mail_sync import MailGateway
from recruitment_agent.application.secure_links import SecureActionLinkService
from recruitment_agent.email.models import NormalizedEmail, PrefilterResult
from recruitment_agent.email.normalizer import EmailNormalizer
from recruitment_agent.email.prefilter import RecruitmentPrefilter
from recruitment_agent.links.models import SecureLink
from recruitment_agent.privacy.models import SanitizedContent
from recruitment_agent.privacy.sanitizer import PrivacySanitizer
from recruitment_agent.privacy.url_discovery import UrlDiscoverer


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class SecurePreparedEmail:
    normalized: NormalizedEmail
    secure_links: tuple[SecureLink, ...]
    sanitized: SanitizedContent
    prefilter: PrefilterResult

    def __repr__(self) -> str:
        return (
            "SecurePreparedEmail("
            f"source_email_id={self.normalized.source_email_id!r}, "
            f"link_count={len(self.secure_links)}, "
            f"prefilter={self.prefilter.decision.value!r})"
        )


class SecureEmailPreparationService:
    """Consume plaintext URLs before emitting sanitized text or safe metadata."""

    def __init__(
        self,
        *,
        gateway: MailGateway,
        link_service: SecureActionLinkService,
        url_discoverer: UrlDiscoverer | None = None,
        normalizer: EmailNormalizer | None = None,
        sanitizer: PrivacySanitizer | None = None,
        prefilter: RecruitmentPrefilter | None = None,
    ) -> None:
        self._gateway = gateway
        self._link_service = link_service
        self._url_discoverer = url_discoverer or UrlDiscoverer()
        self._normalizer = normalizer or EmailNormalizer()
        self._sanitizer = sanitizer or PrivacySanitizer()
        self._prefilter = prefilter or RecruitmentPrefilter()

    async def prepare(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        graph_message_id: str,
    ) -> SecurePreparedEmail:
        mail = await self._gateway.fetch_message(
            account_id=account_id,
            message_id=graph_message_id,
        )
        discovered = self._url_discoverer.discover(
            content_type=mail.body_content_type,
            content=mail.body_content,
        )
        secured = await self._link_service.secure(
            source_email_id=source_email_id,
            discovered_urls=discovered,
            surrounding_text=mail.metadata.subject,
        )
        normalized = self._normalizer.normalize(
            source_email_id=source_email_id,
            mail=mail,
            link_replacements=secured.plaintext_replacements(),
        )
        future_model_input = f"Subject: {normalized.subject}\n\n{normalized.body_text}"
        sanitized = self._sanitizer.sanitize(future_model_input)
        prefilter = self._prefilter.classify(normalized, sanitized_body=sanitized.text)
        return SecurePreparedEmail(
            normalized=normalized,
            secure_links=secured.links,
            sanitized=sanitized,
            prefilter=prefilter,
        )
