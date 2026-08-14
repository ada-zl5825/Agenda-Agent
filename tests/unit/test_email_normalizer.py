from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from recruitment_agent.application.mail_sync import FetchedMail
from recruitment_agent.domain.mail import SourceEmailCandidate
from recruitment_agent.email.normalizer import EmailNormalizer

FIXTURES = Path(__file__).parents[1] / "fixtures" / "emails"


def fetched_mail(
    fixture_name: str,
    *,
    subject: str = "Fwd: recruitment email",
    sender_name: str = "Outer Mailbox",
    sender_address: str = "aggregate@outlook.example",
) -> FetchedMail:
    return FetchedMail(
        metadata=SourceEmailCandidate(
            graph_message_id="graph-1",
            internet_message_id="<one@example.test>",
            subject=subject,
            sender_domain="outlook.example",
            received_at=datetime(2026, 8, 12, 9, tzinfo=UTC),
            outlook_web_link="https://outlook.office.com/mail/graph-1",
            has_attachments=True,
        ),
        sender_name=sender_name,
        sender_address=sender_address,
        body_content_type="html",
        body_content=(FIXTURES / fixture_name).read_text(encoding="utf-8"),
    )


def test_html_normalization_removes_active_hidden_tracking_and_footer_content() -> None:
    normalized = EmailNormalizer().normalize(
        source_email_id=uuid4(),
        mail=fetched_mail("assessment_en.html", subject="Assessment invitation"),
    )

    assert "Online assessment invitation" in normalized.body_text
    assert "Start assessment" in normalized.body_text
    assert "https://" not in normalized.body_text
    assert "candidate@example.test" not in normalized.body_text
    assert "tracking.example.test" not in normalized.body_text
    assert "Footer content" not in normalized.body_text


def test_outlook_126_wrap_without_banner_keeps_original_recruiter() -> None:
    """Regression: Outlook #divRplyFwdMsg must not drop 126 auto-forward headers."""
    normalized = EmailNormalizer().normalize(
        source_email_id=uuid4(),
        mail=fetched_mail(
            "forwarded_outlook_126.html",
            subject="腾讯后台开发工程师一面",
            sender_name="求职邮箱",
            sender_address="candidate@126.com",
        ),
    )

    assert normalized.is_forwarded is True
    assert normalized.sender_address == "zhang.recruiter@company.example"
    assert normalized.sender_domain == "company.example"
    assert normalized.outer_sender_address == "candidate@126.com"
    assert normalized.outer_sender_domain == "126.com"
    assert normalized.subject == "腾讯后台开发工程师一面"
    assert "邀请您参加" in normalized.body_text
    assert "来自 126" not in normalized.body_text


def test_recruiter_reply_quoting_126_does_not_replace_author() -> None:
    mail = FetchedMail(
        metadata=SourceEmailCandidate(
            graph_message_id="graph-reply",
            internet_message_id=None,
            subject="Re: Interview",
            sender_domain="careers.example",
            received_at=datetime(2026, 8, 12, 9, tzinfo=UTC),
            outlook_web_link=None,
            has_attachments=False,
        ),
        sender_name="Alice Recruiter",
        sender_address="alice@careers.example",
        body_content_type="html",
        body_content=(
            "<p>Please confirm the new time.</p>"
            "<div id='divRplyFwdMsg'>"
            "<p>From: Candidate &lt;candidate@126.com&gt;</p>"
            "<p>Sent: Tuesday, 11 August 2026 18:00</p>"
            "<p>To: alice@careers.example</p>"
            "<p>Subject: Interview</p>"
            "</div>"
        ),
    )

    normalized = EmailNormalizer().normalize(source_email_id=uuid4(), mail=mail)

    assert normalized.is_forwarded is False
    assert normalized.sender_address == "alice@careers.example"
    assert normalized.sender_domain == "careers.example"
    assert "Please confirm the new time" in normalized.body_text


def test_126_forward_prefers_original_recruiter_subject_and_body() -> None:
    normalized = EmailNormalizer().normalize(
        source_email_id=uuid4(),
        mail=fetched_mail("forwarded_126.html"),
    )

    assert normalized.is_forwarded is True
    assert normalized.sender_name == "张招聘"
    assert normalized.sender_address == "zhang.recruiter@company.example"
    assert normalized.sender_domain == "company.example"
    assert normalized.subject == "腾讯后台开发工程师一面"
    assert normalized.outer_sender_address == "aggregate@outlook.example"
    assert "邀请您参加" in normalized.body_text
    assert "来自 126" not in normalized.body_text


def test_nested_forward_uses_deepest_original_and_removes_quoted_history() -> None:
    normalized = EmailNormalizer().normalize(
        source_email_id=uuid4(),
        mail=fetched_mail("forwarded_nested.html"),
    )

    assert normalized.sender_address == "alice@careers.example"
    assert normalized.subject == "Graduate Software Engineer Interview"
    assert "invite you to an interview" in normalized.body_text
    assert "older duplicate" not in normalized.body_text
    assert "Nested original follows" not in normalized.body_text


def test_normalized_email_repr_does_not_contain_body_or_private_sender() -> None:
    normalized = EmailNormalizer().normalize(
        source_email_id=uuid4(),
        mail=fetched_mail("forwarded_126.html"),
    )

    representation = repr(normalized)
    assert "邀请您参加" not in representation
    assert "zhang.recruiter@company.example" not in representation


def test_removes_unmarked_blockquote_reply_history() -> None:
    mail = FetchedMail(
        metadata=SourceEmailCandidate(
            graph_message_id="graph-2",
            internet_message_id=None,
            subject="Interview",
            sender_domain="careers.example",
            received_at=datetime(2026, 8, 12, 9, tzinfo=UTC),
            outlook_web_link=None,
            has_attachments=False,
        ),
        sender_name="Recruiter",
        sender_address="recruiter@careers.example",
        body_content_type="html",
        body_content=(
            "<p>Your interview is confirmed.</p>"
            "<blockquote><p>Old private reply content.</p></blockquote>"
        ),
    )

    normalized = EmailNormalizer().normalize(source_email_id=uuid4(), mail=mail)

    assert "interview is confirmed" in normalized.body_text
    assert "Old private reply" not in normalized.body_text


def test_visible_url_anchor_is_replaced_by_one_opaque_reference() -> None:
    raw_url = "https://assessment.example.test/start?token=secret"
    mail = FetchedMail(
        metadata=SourceEmailCandidate(
            graph_message_id="graph-visible-url",
            internet_message_id=None,
            subject="Assessment",
            sender_domain="careers.example",
            received_at=datetime(2026, 8, 12, 9, tzinfo=UTC),
            outlook_web_link=None,
            has_attachments=False,
        ),
        sender_name="Recruiter",
        sender_address="recruiter@careers.example",
        body_content_type="html",
        body_content=f'<a href="{raw_url}">{raw_url}</a>',
    )

    normalized = EmailNormalizer().normalize(
        source_email_id=uuid4(),
        mail=mail,
        link_replacements={raw_url: "[ACTION_LINK_01]"},
    )

    assert normalized.body_text == "[ACTION_LINK_01]"
