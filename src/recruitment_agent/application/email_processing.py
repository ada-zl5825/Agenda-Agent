"""Phase 2 email preparation with an explicit privacy boundary."""

from dataclasses import dataclass
from uuid import UUID

from recruitment_agent.application.mail_sync import MailGateway
from recruitment_agent.email.models import NormalizedEmail, PrefilterResult
from recruitment_agent.email.normalizer import EmailNormalizer
from recruitment_agent.email.prefilter import RecruitmentPrefilter
from recruitment_agent.privacy.models import DiscoveredUrl, SanitizedContent
from recruitment_agent.privacy.sanitizer import PrivacySanitizer
from recruitment_agent.privacy.url_discovery import UrlDiscoverer


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class PreparedEmail:
    """Transient Phase 2 result; raw URL candidates must be consumed by Phase 3."""

    normalized: NormalizedEmail
    discovered_urls: tuple[DiscoveredUrl, ...]
    sanitized: SanitizedContent
    prefilter: PrefilterResult

    def __repr__(self) -> str:
        return (
            "PreparedEmail("
            f"source_email_id={self.normalized.source_email_id!r}, "
            f"url_count={len(self.discovered_urls)}, "
            f"prefilter={self.prefilter.decision.value!r})"
        )


class EmailPreparationService:
    """Fetch and prepare one email without persistence, attachments, or model calls."""

    def __init__(
        self,
        *,
        gateway: MailGateway,
        url_discoverer: UrlDiscoverer | None = None,
        normalizer: EmailNormalizer | None = None,
        sanitizer: PrivacySanitizer | None = None,
        prefilter: RecruitmentPrefilter | None = None,
    ) -> None:
        self._gateway = gateway
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
    ) -> PreparedEmail:
        mail = await self._gateway.fetch_message(
            account_id=account_id,
            message_id=graph_message_id,
        )
        discovered_urls = self._url_discoverer.discover(
            content_type=mail.body_content_type,
            content=mail.body_content,
        )
        normalized = self._normalizer.normalize(source_email_id=source_email_id, mail=mail)
        future_model_input = f"Subject: {normalized.subject}\n\n{normalized.body_text}"
        sanitized = self._sanitizer.sanitize(
            future_model_input,
            discovered_urls=discovered_urls,
        )
        prefilter = self._prefilter.classify(normalized, sanitized_body=sanitized.text)
        return PreparedEmail(
            normalized=normalized,
            discovered_urls=discovered_urls,
            sanitized=sanitized,
            prefilter=prefilter,
        )
