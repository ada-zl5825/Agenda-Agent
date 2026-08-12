"""Deterministic action-link classification without inspecting query values."""

import re
from urllib.parse import unquote_plus, urlsplit

from recruitment_agent.application.errors import LinkExtractionError
from recruitment_agent.links.models import ActionLinkType
from recruitment_agent.privacy.models import DiscoveredUrl


class ActionLinkClassifier:
    """Classify by host/path/query-key and display/body context, never secret values."""

    _MEETING_HOSTS = re.compile(
        r"(?:^|\.)(?:teams\.microsoft\.com|zoom\.us|meet\.google\.com|webex\.com)$",
        re.I,
    )
    _RULES: tuple[tuple[ActionLinkType, re.Pattern[str]], ...] = (
        (
            ActionLinkType.ASSESSMENT,
            re.compile(
                r"(?:assessment|coding[-_ ]?(?:test|challenge)|online[-_ ]?test|"
                r"测评|笔试|hackerrank|codility|hirevue|pymetrics|shl)",
                re.I,
            ),
        ),
        (
            ActionLinkType.SCHEDULING,
            re.compile(
                r"(?:schedul|book[-_ ]?(?:a[-_ ]?)?(?:slot|time)|calendly|goodtime|预约)",
                re.I,
            ),
        ),
        (
            ActionLinkType.CONFIRMATION,
            re.compile(r"(?:confirm|confirmation|accept|rsvp|确认|接受邀请)", re.I),
        ),
        (ActionLinkType.OFFER, re.compile(r"(?:offer|录用)", re.I)),
        (ActionLinkType.INTERVIEW, re.compile(r"(?:interview|面试)", re.I)),
        (
            ActionLinkType.APPLICATION_PORTAL,
            re.compile(
                r"(?:application|applicant|candidate[-_ ]?portal|careers?|jobs?|"
                r"workday|greenhouse|lever|申请|应聘)",
                re.I,
            ),
        ),
    )

    def classify(self, link: DiscoveredUrl, *, surrounding_text: str = "") -> ActionLinkType:
        raw_url = link.url.get_secret_value()
        parsed = urlsplit(raw_url)
        if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
            raise LinkExtractionError("action link uses an unsupported URL scheme")
        host = parsed.hostname.lower()
        if self._MEETING_HOSTS.search(host):
            return ActionLinkType.MEETING
        query_keys = " ".join(
            unquote_plus(component.partition("=")[0])
            for component in parsed.query.split("&")
            if component
        )
        safe_context = " ".join(
            part
            for part in (
                host,
                parsed.path,
                query_keys,
                link.display_text,
                surrounding_text,
            )
            if part
        )
        for link_type, pattern in self._RULES:
            if pattern.search(safe_context):
                return link_type
        return ActionLinkType.GENERAL
