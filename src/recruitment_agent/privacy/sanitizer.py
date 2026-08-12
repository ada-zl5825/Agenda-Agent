"""Final privacy boundary producing text safe for future inference."""

import html
import re

from recruitment_agent.application.errors import PrivacySanitizationError
from recruitment_agent.privacy.models import DiscoveredUrl, SanitizedContent
from recruitment_agent.privacy.pii import PiiRedactor


class PrivacySanitizer:
    _URL = re.compile(r"https?://[^\s<>\"'\[\]]+", re.IGNORECASE)
    _MAILTO = re.compile(r"mailto:[^\s<>\"']+", re.IGNORECASE)

    def __init__(self, pii_redactor: PiiRedactor | None = None) -> None:
        self._pii_redactor = pii_redactor or PiiRedactor()

    def sanitize(
        self,
        text: str,
        *,
        discovered_urls: tuple[DiscoveredUrl, ...] = (),
    ) -> SanitizedContent:
        try:
            sanitized = html.unescape(text)
            url_count = 0
            for discovered in sorted(
                discovered_urls,
                key=lambda item: len(item.url.get_secret_value()),
                reverse=True,
            ):
                raw_url = discovered.url.get_secret_value()
                sanitized, count = re.subn(
                    re.escape(raw_url),
                    "[URL_REDACTED]",
                    sanitized,
                    flags=re.IGNORECASE,
                )
                if count == 0:
                    decoded_url = html.unescape(raw_url)
                    sanitized, count = re.subn(
                        re.escape(decoded_url),
                        "[URL_REDACTED]",
                        sanitized,
                        flags=re.IGNORECASE,
                    )
                url_count += count
            sanitized, remaining_url_count = self._URL.subn("[URL_REDACTED]", sanitized)
            sanitized, mailto_count = self._MAILTO.subn("[EMAIL_REDACTED]", sanitized)
            sanitized, pii_counts = self._pii_redactor.redact(sanitized)
            counts = dict(pii_counts)
            if url_count + remaining_url_count:
                counts["url"] = url_count + remaining_url_count
            if mailto_count:
                counts["email"] = counts.get("email", 0) + mailto_count
            sanitized = re.sub(r"[ \t]+", " ", sanitized)
            sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
        except (TypeError, ValueError) as exc:
            raise PrivacySanitizationError("email content could not be sanitized") from exc
        if self._URL.search(sanitized):
            raise PrivacySanitizationError("URL remained after privacy sanitization")
        return SanitizedContent(text=sanitized, redaction_counts=counts)
