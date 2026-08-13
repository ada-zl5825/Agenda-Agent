from datetime import UTC, datetime
from uuid import uuid4

from recruitment_agent.application.calendar_sync import CalendarPlanner
from recruitment_agent.calendar.models import CalendarCandidate
from recruitment_agent.domain.enums import EventStatus, RecruitmentEventType


def test_calendar_draft_excludes_action_tokens_and_untrusted_urls() -> None:
    secret = "candidate-token-plaintext"
    candidate = CalendarCandidate(
        account_id=uuid4(),
        source_email_id=uuid4(),
        recruitment_event_id=uuid4(),
        application_id=uuid4(),
        application_resolved=True,
        company_display_name="Example",
        role_name="Engineer",
        event_type=RecruitmentEventType.ASSESSMENT,
        event_status=EventStatus.ACTIVE,
        interview_round=None,
        starts_at=None,
        deadline_at=datetime(2026, 8, 20, 17, tzinfo=UTC),
        timezone="Europe/London",
        source_datetime_text=f"Complete at https://assessment.test/?token={secret}",
        outlook_web_link=f"https://assessment.test/?token={secret}",
    )

    plan = CalendarPlanner().plan(candidate, has_existing_link=False)

    assert plan.draft is not None
    assert secret not in plan.draft.body
    assert "assessment.test" not in plan.draft.body
    assert "ACTION_LINK_" not in plan.draft.body
