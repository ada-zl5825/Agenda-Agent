from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from recruitment_agent.email.models import NormalizedEmail, PrefilterDecision
from recruitment_agent.email.prefilter import RecruitmentPrefilter

FIXTURES = Path(__file__).parents[1] / "fixtures" / "emails"


def normalized_email(*, subject: str, body: str, domain: str = "example.test") -> NormalizedEmail:
    return NormalizedEmail(
        source_email_id=uuid4(),
        graph_message_id="graph-1",
        internet_message_id=None,
        subject=subject,
        sender_name=None,
        sender_address=None,
        sender_domain=domain,
        outer_sender_name=None,
        outer_sender_address=None,
        outer_sender_domain=None,
        received_at=datetime(2026, 8, 12, tzinfo=UTC),
        body_text=body,
        outlook_web_link=None,
        has_attachments=False,
        is_forwarded=False,
    )


def test_prefilter_detects_chinese_and_english_recruitment_terms() -> None:
    prefilter = RecruitmentPrefilter()

    chinese = prefilter.classify(
        normalized_email(subject="腾讯后台开发工程师一面", body="邀请您参加面试"),
        sanitized_body="邀请您参加面试",
    )
    english = prefilter.classify(
        normalized_email(subject="An update", body="Interview invitation"),
        sanitized_body="We invite you to an interview.",
    )

    assert chinese.decision is PrefilterDecision.LIKELY_RECRUITMENT
    assert english.decision is PrefilterDecision.LIKELY_RECRUITMENT


def test_prefilter_is_conservative_for_unknown_mail() -> None:
    result = RecruitmentPrefilter().classify(
        normalized_email(subject="A message", body="Please read this update"),
        sanitized_body="Please read this update",
    )

    assert result.decision is PrefilterDecision.UNKNOWN


def test_prefilter_rejects_only_clear_non_recruitment_subject() -> None:
    body = (FIXTURES / "non_recruitment.html").read_text(encoding="utf-8")
    result = RecruitmentPrefilter().classify(
        normalized_email(subject="您的快递派送通知", body=body),
        sanitized_body="包裹已到达附近站点。",
    )

    assert result.decision is PrefilterDecision.UNLIKELY
