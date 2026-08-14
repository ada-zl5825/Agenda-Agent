"""Parse common 126-to-Outlook and RFC-style forwarded message headers."""

import html
import re
from dataclasses import dataclass

from recruitment_agent.email.models import ForwardedEnvelope


@dataclass(frozen=True, slots=True)
class _HeaderBlock:
    start: int
    body_start: int
    sender_name: str | None
    sender_address: str | None
    subject: str | None
    explicit_marker: bool


class ForwardedMailParser:
    """Select the deepest original sender context from nested forwards."""

    _HEADER = re.compile(
        r"^\s*(?P<name>from|发件人|寄件者|sender|subject|主题|主旨)\s*[:\uff1a]\s*"
        r"(?P<value>.*?)\s*$",
        re.IGNORECASE,
    )
    _FROM_NAMES = frozenset({"from", "发件人", "寄件者", "sender"})
    _SUBJECT_NAMES = frozenset({"subject", "主题", "主旨"})
    _FORWARD_MARKER = re.compile(
        r"(?:-{2,}\s*(?:forwarded message|original message|转发的邮件|原始邮件)\s*-{2,})",
        re.IGNORECASE,
    )
    _ANGLE_ADDRESS = re.compile(
        r"^(?P<name>.*?)\s*[<\uff08(]\s*(?:mailto:)?"
        r"(?P<address>[^>\uff09)\s]+@[^>\uff09)\s]+)\s*[>\uff09)]$",
        re.IGNORECASE,
    )
    _BARE_ADDRESS = re.compile(r"(?P<address>[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,})")

    def parse(self, body_text: str) -> ForwardedEnvelope | None:
        lines = body_text.splitlines()
        blocks = self._find_header_blocks(lines)
        if not blocks:
            return None
        selected = blocks[-1]
        forwarded_body = "\n".join(lines[selected.body_start :]).strip()
        return ForwardedEnvelope(
            sender_name=selected.sender_name,
            sender_address=selected.sender_address,
            subject=selected.subject,
            body_text=forwarded_body,
            depth=len(blocks),
            has_explicit_marker=any(block.explicit_marker for block in blocks),
        )

    def _find_header_blocks(self, lines: list[str]) -> list[_HeaderBlock]:
        blocks: list[_HeaderBlock] = []
        for index, line in enumerate(lines):
            match = self._HEADER.match(line)
            if match is None or match.group("name").lower() not in self._FROM_NAMES:
                continue
            looks_forwarded, explicit_marker = self._looks_forwarded(lines, index)
            if not looks_forwarded:
                continue
            sender_value, consumed = self._header_value(lines, index, match.group("value"))
            sender_name, sender_address = self._parse_sender(sender_value)
            subject: str | None = None
            body_start = consumed + 1
            for header_index in range(consumed + 1, min(len(lines), consumed + 14)):
                header_match = self._HEADER.match(lines[header_index])
                if header_match is not None:
                    header_name = header_match.group("name").lower()
                    header_value, value_index = self._header_value(
                        lines,
                        header_index,
                        header_match.group("value"),
                    )
                    if header_name in self._SUBJECT_NAMES:
                        subject = self._clean_subject(header_value)
                    body_start = value_index + 1
                    continue
                normalized = lines[header_index].strip().lower()
                if not normalized:
                    body_start = header_index + 1
                    continue
                if self._is_auxiliary_header(normalized):
                    body_start = header_index + 1
                    if header_index + 1 < len(lines):
                        nxt = lines[header_index + 1].strip()
                        if (
                            nxt
                            and self._HEADER.match(lines[header_index + 1]) is None
                            and not self._is_auxiliary_header(nxt)
                        ):
                            body_start = header_index + 2
                    continue
                break
            blocks.append(
                _HeaderBlock(
                    start=index,
                    body_start=body_start,
                    sender_name=sender_name,
                    sender_address=sender_address,
                    subject=subject,
                    explicit_marker=explicit_marker,
                )
            )
        return blocks

    def _looks_forwarded(self, lines: list[str], index: int) -> tuple[bool, bool]:
        preceding = " ".join(lines[max(0, index - 3) : index])
        if self._FORWARD_MARKER.search(preceding):
            return True, True
        header_names = 0
        for line in lines[index + 1 : min(len(lines), index + 8)]:
            normalized = line.strip().lower()
            if self._is_auxiliary_header(normalized) or self._HEADER.match(line):
                header_names += 1
        return (True, False) if header_names >= 2 else (False, False)

    @staticmethod
    def _is_auxiliary_header(line: str) -> bool:
        return bool(
            re.match(
                r"^(?:sent|date|to|cc|发送时间|日期|收件人|抄送)\s*[:\uff1a]",
                line,
                re.IGNORECASE,
            )
        )

    def _header_value(
        self,
        lines: list[str],
        index: int,
        raw_value: str,
    ) -> tuple[str, int]:
        """Accept Outlook's 'From:' / value split across two text nodes."""
        value = raw_value.strip()
        if value or index + 1 >= len(lines):
            return value, index
        nxt = lines[index + 1].strip()
        if (
            not nxt
            or self._HEADER.match(lines[index + 1]) is not None
            or self._is_auxiliary_header(nxt)
        ):
            return value, index
        return nxt, index + 1

    def _parse_sender(self, raw_value: str) -> tuple[str | None, str | None]:
        value = html.unescape(raw_value).strip().strip('"')
        angle_match = self._ANGLE_ADDRESS.match(value)
        if angle_match is not None:
            name = angle_match.group("name").strip().strip('"') or None
            return name, angle_match.group("address").lower()
        address_match = self._BARE_ADDRESS.search(value)
        if address_match is None:
            return value or None, None
        address = address_match.group("address").lower()
        name = value[: address_match.start()].strip(" \t<>()[]\"") or None
        return name, address

    @staticmethod
    def _clean_subject(value: str) -> str:
        return re.sub(
            r"^(?:(?:fw|fwd|转发)\s*[:\uff1a]\s*)+",
            "",
            value.strip(),
            flags=re.I,
        )
