"""Provider-neutral email normalizer with original forwarded-message precedence."""

from collections.abc import Mapping
from urllib.parse import urlsplit
from uuid import UUID

from recruitment_agent.application.mail_sync import FetchedMail
from recruitment_agent.domain.company import is_consumer_mailbox_domain
from recruitment_agent.email.forwarded_parser import ForwardedMailParser
from recruitment_agent.email.html_normalizer import HtmlBodyNormalizer
from recruitment_agent.email.models import ForwardedEnvelope, NormalizedEmail


class EmailNormalizer:
    def __init__(
        self,
        *,
        body_normalizer: HtmlBodyNormalizer | None = None,
        forwarded_parser: ForwardedMailParser | None = None,
    ) -> None:
        self._body_normalizer = body_normalizer or HtmlBodyNormalizer()
        self._forwarded_parser = forwarded_parser or ForwardedMailParser()

    def normalize(
        self,
        *,
        source_email_id: UUID,
        mail: FetchedMail,
        link_replacements: Mapping[str, str] | None = None,
    ) -> NormalizedEmail:
        body_text = self._body_normalizer.normalize(
            content_type=mail.body_content_type,
            content=mail.body_content,
            link_replacements=link_replacements,
        )
        forwarded = self._forwarded_parser.parse(body_text)
        adopt_inner = self._adopt_forwarded_envelope(
            outer_address=mail.sender_address,
            outer_domain=mail.metadata.sender_domain,
            forwarded=forwarded,
        )
        effective_body = (
            forwarded.body_text if adopt_inner and forwarded is not None else body_text
        )
        effective_body = self._body_normalizer.clean_text(effective_body)
        effective_name = (
            forwarded.sender_name
            if adopt_inner and forwarded is not None and forwarded.sender_name is not None
            else mail.sender_name
        )
        effective_address = (
            forwarded.sender_address
            if adopt_inner and forwarded is not None and forwarded.sender_address is not None
            else mail.sender_address
        )
        effective_subject = (
            forwarded.subject
            if adopt_inner and forwarded is not None and forwarded.subject is not None
            else mail.metadata.subject
        )
        return NormalizedEmail(
            source_email_id=source_email_id,
            graph_message_id=mail.metadata.graph_message_id,
            internet_message_id=mail.metadata.internet_message_id,
            subject=effective_subject,
            sender_name=effective_name,
            sender_address=effective_address,
            sender_domain=self._domain(effective_address) or mail.metadata.sender_domain,
            outer_sender_name=mail.sender_name,
            outer_sender_address=mail.sender_address,
            outer_sender_domain=self._domain(mail.sender_address) or mail.metadata.sender_domain,
            received_at=mail.metadata.received_at,
            body_text=effective_body,
            outlook_web_link=mail.metadata.outlook_web_link,
            has_attachments=mail.metadata.has_attachments,
            is_forwarded=adopt_inner,
        )

    @classmethod
    def _adopt_forwarded_envelope(
        cls,
        *,
        outer_address: str | None,
        outer_domain: str | None,
        forwarded: ForwardedEnvelope | None,
    ) -> bool:
        """Use the inner recruiter only for real forwards, not reply quotes.

        126 auto-forwards arrive in Outlook with a consumer outer From. The
        original recruiter lives in the inlined headers. A recruiter *reply*
        that quotes the 126 mailbox must keep the Graph author, otherwise every
        later message collapses onto 126.com and duplicate-event matching
        attaches the wrong company.
        """
        if forwarded is None or forwarded.sender_address is None:
            return False
        outer = cls._domain(outer_address) or outer_domain
        inner = cls._domain(forwarded.sender_address)
        if is_consumer_mailbox_domain(outer) and not is_consumer_mailbox_domain(inner):
            return True
        if is_consumer_mailbox_domain(inner) and not is_consumer_mailbox_domain(outer):
            return False
        return forwarded.has_explicit_marker

    @staticmethod
    def _domain(address: str | None) -> str | None:
        if address is None or "@" not in address:
            return None
        domain = address.rsplit("@", maxsplit=1)[1].strip().lower()
        parsed = urlsplit(f"https://{domain}")
        return parsed.hostname
