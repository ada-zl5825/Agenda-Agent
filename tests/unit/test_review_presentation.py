from datetime import UTC, datetime
from uuid import uuid4

from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem
from recruitment_agent.reviews.presentation import (
    clock_field_copy,
    review_action_label,
    review_headline,
)
from recruitment_agent.reviews.renderer import ReviewHtmlRenderer


def test_queue_leads_with_company_and_action_not_error_codes() -> None:
    html = ReviewHtmlRenderer().queue(
        (
            ReviewQueueItem(
                id=uuid4(),
                source_email_id=uuid4(),
                review_type="TIMEZONE_AMBIGUITY",
                reason="timezone_ambiguity",
                created_at=datetime(2026, 8, 14, 12, tzinfo=UTC),
                company="字节跳动",
                role="软件工程师",
                subject="面试邀请",
                event_type="interview",
                source_time_text="8月20日下午3点",
            ),
        )
    )

    assert "字节跳动 · 软件工程师" in html
    assert "确认时区" in html
    assert "面试" in html
    assert "8月20日下午3点" in html
    assert "TIMEZONE_AMBIGUITY" not in html
    assert "timezone_ambiguity" not in html


def test_datetime_override_labels_start_versus_deadline() -> None:
    start_label, start_hint = clock_field_copy("datetime_unresolved")
    deadline_label, deadline_hint = clock_field_copy("deadline_unresolved")

    assert start_label == "开始时间"
    assert "不是结束时间" in start_hint
    assert deadline_label == "截止日期"
    assert "不是面试结束时间" in deadline_hint


def test_detail_form_says_start_time_for_unresolved_event_clock() -> None:
    detail = ReviewDetail(
        id=uuid4(),
        account_id=uuid4(),
        processing_run_id=uuid4(),
        source_email_id=uuid4(),
        review_type="DATETIME_CONFLICT",
        status="open",
        reason="datetime_unresolved",
        question="请填写开始时间",
        allowed_choices=("use_override", "ignore"),
        version=1,
        created_at=datetime(2026, 8, 14, 12, tzinfo=UTC),
        resolved_at=None,
        resolution=None,
        run_status="needs_review",
        source={"subject": "Interview"},
        application={"company_raw": "Contoso", "role_raw": "Analyst"},
        extraction={"event_type": "interview"},
        validation_findings=(),
        current_values={},
        proposed_values={},
        candidates=(),
        secure_links=(),
        side_effects=(),
    )

    html = ReviewHtmlRenderer().detail(detail, csrf_token="csrf")

    assert "Contoso · Analyst" in html
    assert "补全面试开始时间" in html
    assert "开始时间" in html
    assert "不是结束时间" in html
    assert "DATETIME_CONFLICT" in html


def test_review_headline_falls_back_to_subject() -> None:
    assert review_headline(company=None, role=None, subject="Fwd: Interview") == "Fwd: Interview"
    assert review_action_label("APPLICATION_AMBIGUITY", "company_unresolved") == "确认公司和申请"
