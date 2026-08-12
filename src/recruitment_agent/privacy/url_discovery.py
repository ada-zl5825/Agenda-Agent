"""Discover HTTP(S) action-link candidates before destructive HTML sanitization."""

import html
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import SecretStr

from recruitment_agent.privacy.models import DiscoveredUrl, UrlSource


class UrlDiscoverer:
    """Preserve exact raw URLs transiently for the future Phase 3 encryption boundary."""

    _PLAIN_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
    _TRAILING_PUNCTUATION = ".,;:!?\uff0c\u3002\uff1b\uff1a\uff01\uff1f)]}\uff09\u3011\u300d\u300f"
    _HIDDEN_STYLE = re.compile(
        r"(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:[;\s]|$))",
        re.IGNORECASE,
    )

    def discover(self, *, content_type: str, content: str) -> tuple[DiscoveredUrl, ...]:
        candidates: list[tuple[str, str | None, UrlSource]] = []
        if content_type.lower() == "html":
            soup = BeautifulSoup(content, "lxml")
            for tag in soup.find_all(["script", "style", "noscript", "template"]):
                tag.decompose()
            for anchor in soup.find_all("a", href=True):
                if self._is_hidden(anchor):
                    continue
                href = anchor.get("href")
                if isinstance(href, str):
                    candidates.append(
                        (
                            html.unescape(href).strip(),
                            anchor.get_text(" ", strip=True) or None,
                            UrlSource.HTML_LINK,
                        )
                    )
            visible_text = soup.get_text(" ")
        else:
            visible_text = html.unescape(content)
        candidates.extend(
            (match.group(0).rstrip(self._TRAILING_PUNCTUATION), None, UrlSource.PLAIN_TEXT)
            for match in self._PLAIN_URL.finditer(visible_text)
        )

        discovered: list[DiscoveredUrl] = []
        seen: set[str] = set()
        for raw_url, display_text, source in candidates:
            parsed = urlsplit(raw_url)
            if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
                continue
            if raw_url in seen:
                continue
            seen.add(raw_url)
            discovered.append(
                DiscoveredUrl(
                    ordinal=len(discovered) + 1,
                    url=SecretStr(raw_url),
                    domain=parsed.hostname.lower(),
                    display_text=display_text,
                    source=source,
                )
            )
        return tuple(discovered)

    def _is_hidden(self, anchor: object) -> bool:
        current = anchor
        while hasattr(current, "attrs"):
            attrs = getattr(current, "attrs", {})
            if "hidden" in attrs or attrs.get("aria-hidden") == "true":
                return True
            style = attrs.get("style")
            if isinstance(style, str) and self._HIDDEN_STYLE.search(style):
                return True
            current = getattr(current, "parent", None)
            if current is None:
                break
        return False
