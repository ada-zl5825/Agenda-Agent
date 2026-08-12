from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from recruitment_agent.application.email_processing import EmailPreparationService
from recruitment_agent.application.mail_sync import FetchedMail, MailDeltaPage
from recruitment_agent.domain.mail import SourceEmailCandidate
from recruitment_agent.email.models import PrefilterDecision
from recruitment_agent.privacy.sanitizer import PrivacySanitizer
from recruitment_agent.privacy.url_discovery import UrlDiscoverer

FIXTURES = Path(__file__).parents[1] / "fixtures" / "emails"


def raw_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class MailGateway:
    def __init__(self, body: str, *, subject: str = "字节跳动在线测评") -> None:
        self.body = body
        self.subject = subject
        self.message_fetches = 0

    async def fetch_delta_page(
        self,
        *,
        account_id: UUID,
        folder_id: str,
        cursor: str | None,
    ) -> MailDeltaPage:
        del account_id, folder_id, cursor
        raise AssertionError("delta synchronization is not part of email preparation")

    async def fetch_message(self, *, account_id: UUID, message_id: str) -> FetchedMail:
        del account_id
        self.message_fetches += 1
        return FetchedMail(
            metadata=SourceEmailCandidate(
                graph_message_id=message_id,
                internet_message_id="<one@example.test>",
                subject=self.subject,
                sender_domain="example.test",
                received_at=datetime(2026, 8, 12, 9, tzinfo=UTC),
                outlook_web_link=None,
                has_attachments=True,
            ),
            sender_name="Recruiter",
            sender_address="recruiter@example.test",
            body_content_type="html",
            body_content=self.body,
        )


def test_url_discovery_preserves_exact_secret_transiently_but_hides_repr() -> None:
    discovered = UrlDiscoverer().discover(
        content_type="html",
        content=raw_fixture("tokenized_assessment_link.html"),
    )

    assert len(discovered) == 2
    assert (
        discovered[0].url.get_secret_value()
        == "https://assessment.example.test/start?token=fake-sensitive-token&candidate=fake-9988"
    )
    assert discovered[0].display_text == "Open test"
    assert discovered[0].domain == "assessment.example.test"
    assert "fake-sensitive-token" not in repr(discovered[0])


def test_url_discovery_ignores_script_and_inline_hidden_links() -> None:
    content = """
    <script>const url = "https://tracking.example.test/script";</script>
    <a hidden href="https://tracking.example.test/hidden">hidden</a>
    <a href="https://careers.example.test/interview">Interview</a>
    """

    discovered = UrlDiscoverer().discover(content_type="html", content=content)

    assert len(discovered) == 1
    assert discovered[0].domain == "careers.example.test"


def test_sanitizer_is_idempotent() -> None:
    sanitizer = PrivacySanitizer()
    first = sanitizer.sanitize(
        "Email candidate@example.test and open https://example.test/?token=fake."
    )
    second = sanitizer.sanitize(first.text)

    assert second.text == first.text
    assert "URL_REDACTED" in second.text
    assert "EMAIL_REDACTED" in second.text


def test_sanitizer_removes_urls_and_all_required_pii_without_changing_datetime() -> None:
    text = """
    面试时间: 2026-08-20 15:00 CST
    联系方式: candidate@example.test, +86 138 0000 0000
    候选人编号: CAND-FAKE-42
    学号: STU-2026-0001
    身份证: 110101199001011234
    Passport No: P12345678
    Link: https://assessment.example.test/start?token=fake-token&candidate=fake-id
    """
    discovered = UrlDiscoverer().discover(content_type="text", content=text)
    result = PrivacySanitizer().sanitize(text, discovered_urls=discovered)

    assert "2026-08-20 15:00 CST" in result.text
    assert "candidate@example.test" not in result.text
    assert "138 0000 0000" not in result.text
    assert "CAND-FAKE-42" not in result.text
    assert "STU-2026-0001" not in result.text
    assert "110101199001011234" not in result.text
    assert "P12345678" not in result.text
    assert "https://" not in result.text
    assert "fake-token" not in result.text
    assert result.redaction_counts == {
        "email": 1,
        "government_id": 1,
        "passport": 1,
        "student_id": 1,
        "candidate_id": 1,
        "phone": 1,
        "url": 1,
    }


@pytest.mark.asyncio
async def test_preparation_discovers_before_normalization_and_exposes_only_sanitized_text() -> None:
    body = raw_fixture("assessment_cn.html")
    gateway = MailGateway(body)
    result = await EmailPreparationService(gateway=gateway).prepare(
        account_id=uuid4(),
        source_email_id=uuid4(),
        graph_message_id="graph-1",
    )

    assert gateway.message_fetches == 1
    assert len(result.discovered_urls) == 1
    assert "开始测评" in result.normalized.body_text
    assert "https://" not in result.normalized.body_text
    assert "fake-123" not in result.sanitized.text
    assert "recruiter@example.test" not in result.sanitized.text
    assert "138 0000 0000" not in result.sanitized.text
    assert "110101199001011234" not in result.sanitized.text
    assert "must-not-appear" not in result.sanitized.text
    assert result.prefilter.decision is PrefilterDecision.LIKELY_RECRUITMENT
    assert "not-a-real-secret" not in repr(result)


@pytest.mark.asyncio
async def test_processing_is_deterministic_and_does_not_download_attachments() -> None:
    gateway = MailGateway(raw_fixture("assessment_en.html"))
    service = EmailPreparationService(gateway=gateway)
    account_id = uuid4()
    source_email_id = uuid4()

    first = await service.prepare(
        account_id=account_id,
        source_email_id=source_email_id,
        graph_message_id="graph-1",
    )
    second = await service.prepare(
        account_id=account_id,
        source_email_id=source_email_id,
        graph_message_id="graph-1",
    )

    assert first == second
    assert first.normalized.has_attachments is True
    assert gateway.message_fetches == 2


@pytest.mark.asyncio
async def test_transient_mail_repr_never_exposes_raw_body_or_sender_address() -> None:
    gateway = MailGateway(raw_fixture("tokenized_assessment_link.html"))
    mail = await gateway.fetch_message(account_id=uuid4(), message_id="graph-1")

    representation = repr(mail)
    assert "fake-sensitive-token" not in representation
    assert "recruiter@example.test" not in representation
    assert "graph-1" in representation


@pytest.mark.asyncio
async def test_future_model_text_sanitizes_subject_as_well_as_body() -> None:
    gateway = MailGateway(
        "<p>Interview details follow.</p>",
        subject=(
            "Interview for candidate@example.test "
            "https://careers.example.test/open?token=fake-subject-token"
        ),
    )

    result = await EmailPreparationService(gateway=gateway).prepare(
        account_id=uuid4(),
        source_email_id=uuid4(),
        graph_message_id="graph-1",
    )

    assert "candidate@example.test" not in result.sanitized.text
    assert "fake-subject-token" not in result.sanitized.text
    assert "[EMAIL_REDACTED]" in result.sanitized.text
    assert "[URL_REDACTED]" in result.sanitized.text
