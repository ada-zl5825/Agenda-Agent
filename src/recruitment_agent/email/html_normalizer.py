"""HTML-to-text normalization with active, hidden, tracking, and quoted content removal."""

import html
import re
from collections.abc import Mapping

from bs4 import BeautifulSoup, Comment, Tag

from recruitment_agent.application.errors import EmailNormalizationError


class HtmlBodyNormalizer:
    """Create deterministic readable text without copying hyperlink targets into it."""

    _HIDDEN_STYLE = re.compile(
        r"(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:[;\s]|$)|"
        r"font-size\s*:\s*0(?:px)?|max-height\s*:\s*0(?:px)?)",
        re.IGNORECASE,
    )
    _QUOTED_START = (
        re.compile(r"^on .+wrote:\s*$", re.IGNORECASE),
        re.compile(r"^在.+写道[\uff1a:]\s*$"),
    )
    _FOOTER_START = (
        re.compile(r"^this (?:email|message) and any attachments", re.IGNORECASE),
        re.compile(r"^confidentiality notice", re.IGNORECASE),
        re.compile(r"^本邮件及其附件"),
        re.compile(r"^(?:unsubscribe|退订)(?:\s|$)", re.IGNORECASE),
    )

    def normalize(
        self,
        *,
        content_type: str,
        content: str,
        link_replacements: Mapping[str, str] | None = None,
    ) -> str:
        replacements = link_replacements or {}
        try:
            if content_type.lower() == "html":
                text = self._html_to_text(content, link_replacements=replacements)
            elif content_type.lower() == "text":
                text = self._replace_plain_urls(html.unescape(content), replacements)
            else:
                raise EmailNormalizationError("unsupported message body content type")
        except EmailNormalizationError:
            raise
        except (ValueError, TypeError) as exc:
            raise EmailNormalizationError("message body could not be normalized") from exc
        return self.clean_text(text)

    def _html_to_text(self, content: str, *, link_replacements: Mapping[str, str]) -> str:
        soup = BeautifulSoup(content, "lxml")
        for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
            node.extract()
        self._remove_simple_css_hidden_nodes(soup)
        for tag in soup.find_all(["script", "style", "noscript", "template", "svg", "canvas"]):
            tag.decompose()
        for tag in tuple(soup.find_all(True)):
            if tag.parent is not None and self._is_hidden(tag):
                tag.decompose()
        for quoted in tuple(soup.find_all("blockquote")):
            if quoted.parent is not None and self._is_quoted_history(quoted):
                quoted.decompose()
        for quoted in tuple(soup.find_all("div")):
            if quoted.parent is not None and self._is_quoted_history(quoted):
                quoted.decompose()
        for image in soup.find_all("img"):
            image.decompose()
        for line_break in soup.find_all("br"):
            line_break.replace_with("\n")
        for anchor in soup.find_all("a"):
            label = anchor.get_text(" ", strip=True)
            href = anchor.get("href")
            replacement = None
            normalized_href = None
            if isinstance(href, str):
                normalized_href = html.unescape(href).strip()
                replacement = link_replacements.get(normalized_href)
            if replacement is not None and label == normalized_href:
                label = ""
            anchor.replace_with(" ".join(part for part in (label, replacement) if part) or "[LINK]")
        return self._replace_plain_urls(soup.get_text("\n"), link_replacements)

    def clean_text(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
        raw_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.splitlines()]
        lines: list[str] = []
        seen_substantial: set[str] = set()
        for line in raw_lines:
            if any(pattern.match(line) for pattern in self._QUOTED_START):
                break
            if any(pattern.match(line) for pattern in self._FOOTER_START):
                break
            if line.startswith(">"):
                continue
            if not line:
                if lines and lines[-1]:
                    lines.append("")
                continue
            fingerprint = re.sub(r"\s+", " ", line).casefold()
            if len(fingerprint) >= 24 and fingerprint in seen_substantial:
                continue
            if len(fingerprint) >= 24:
                seen_substantial.add(fingerprint)
            lines.append(line)
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines).strip()

    def _is_hidden(self, tag: Tag) -> bool:
        if tag.has_attr("hidden") or tag.get("aria-hidden") == "true":
            return True
        style = tag.get("style")
        return isinstance(style, str) and self._HIDDEN_STYLE.search(style) is not None

    @staticmethod
    def _replace_plain_urls(text: str, replacements: Mapping[str, str]) -> str:
        replaced = text
        for raw_url, replacement in sorted(
            replacements.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            replaced = replaced.replace(raw_url, replacement)
        return replaced

    def _remove_simple_css_hidden_nodes(self, soup: BeautifulSoup) -> None:
        for style in soup.find_all("style"):
            css = style.get_text(" ")
            for selectors, declaration in re.findall(r"([^{}]+)\{([^{}]+)\}", css):
                if self._HIDDEN_STYLE.search(declaration) is None:
                    continue
                for selector in selectors.split(","):
                    normalized = selector.strip()
                    if not re.fullmatch(r"[.#][A-Za-z_][\w-]*", normalized):
                        continue
                    for hidden in soup.select(normalized):
                        hidden.decompose()

    def _is_quoted_history(self, tag: Tag) -> bool:
        text = tag.get_text(" ", strip=True)
        if re.search(
            r"(?:forwarded message|original message|转发的邮件|原始邮件)",
            text,
            re.IGNORECASE,
        ):
            return False
        raw_classes = tag.get("class")
        if isinstance(raw_classes, str):
            classes = {raw_classes.lower()}
        elif raw_classes is None:
            classes = set()
        else:
            classes = {str(value).lower() for value in raw_classes}
        tag_id = str(tag.get("id", "")).lower()
        return (
            tag.name == "blockquote"
            or bool(classes & {"gmail_quote", "yahoo_quoted", "moz-cite-prefix"})
            or tag_id in {"divrplyfwdmsg", "replyforwardmessage"}
        )
