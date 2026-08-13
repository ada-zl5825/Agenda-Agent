"""Turn discovered URLs into stable opaque action-link candidates."""

from urllib.parse import urlsplit

from recruitment_agent.links.classifier import ActionLinkClassifier
from recruitment_agent.links.models import ActionLinkCandidate
from recruitment_agent.privacy.models import DiscoveredUrl
from recruitment_agent.privacy.sanitizer import PrivacySanitizer


class ActionLinkExtractor:
    def __init__(
        self,
        classifier: ActionLinkClassifier | None = None,
        display_sanitizer: PrivacySanitizer | None = None,
    ) -> None:
        self._classifier = classifier or ActionLinkClassifier()
        self._display_sanitizer = display_sanitizer or PrivacySanitizer()

    def extract(
        self,
        links: tuple[DiscoveredUrl, ...],
        *,
        surrounding_text: str = "",
    ) -> tuple[ActionLinkCandidate, ...]:
        return tuple(
            ActionLinkCandidate(
                ref=f"ACTION_LINK_{index:02d}",
                url=link.url,
                link_type=self._classifier.classify(
                    link,
                    surrounding_text=surrounding_text,
                ),
                domain=urlsplit(link.url.get_secret_value()).hostname or link.domain,
                display_text=self._sanitize_display_text(link.display_text),
            )
            for index, link in enumerate(links, start=1)
        )

    def _sanitize_display_text(self, display_text: str | None) -> str | None:
        if display_text is None:
            return None
        sanitized = self._display_sanitizer.sanitize(display_text).text
        return sanitized or None
