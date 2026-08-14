from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from recruitment_agent.api.app import create_app
from recruitment_agent.api.dependencies import get_review_service, get_web_session_manager
from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem
from recruitment_agent.web.security import WebSessionManager


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, 8, tzinfo=UTC)


def detail(account_id: UUID, review_id: UUID) -> ReviewDetail:
    return ReviewDetail(
        id=review_id,
        account_id=account_id,
        processing_run_id=uuid4(),
        source_email_id=uuid4(),
        review_type="TIMEZONE_AMBIGUITY",
        status="open",
        reason="TIMEZONE_MISSING",
        question="Which timezone applies?",
        allowed_choices=("Europe/London", "Europe/Paris", "other"),
        version=1,
        created_at=datetime(2026, 8, 13, 7, tzinfo=UTC),
        resolved_at=None,
        resolution=None,
        run_status="needs_review",
        source={
            "subject": (
                "Interview <script>alert(1)</script> for candidate@example.test "
                "https://secret.example/start?token=plaintext"
            ),
            "sender_domain": "example.test",
            "received_at": datetime(2026, 8, 13, 7, tzinfo=UTC),
            "open_original_email": "https://outlook.office.com/mail/id/safe",
        },
        application={"company": "Example", "role": "Engineer"},
        extraction={"source_datetime_text": "Friday at 10"},
        validation_findings=("TIMEZONE_REQUIRED",),
        current_values={"timezone": None},
        proposed_values={"timezone": None},
        candidates=(),
        secure_links=(
            {
                "ref": "ACTION_LINK_01",
                "link_type": "meeting",
                "domain": "meet.example.test",
            },
        ),
        side_effects=("Calendar: blocked until this decision is validated",),
    )


class Reviews:
    def __init__(self, value: ReviewDetail) -> None:
        self.value = value
        self.resolutions: list[dict[str, object]] = []

    async def list_open(self, *, account_id: UUID) -> tuple[ReviewQueueItem, ...]:
        assert account_id == self.value.account_id
        return (
            ReviewQueueItem(
                id=self.value.id,
                review_type=self.value.review_type,
                reason=self.value.reason,
                created_at=self.value.created_at,
                company="Example",
                role="Engineer",
            ),
        )

    async def get_detail(self, *, account_id: UUID, review_id: UUID) -> ReviewDetail:
        assert (account_id, review_id) == (self.value.account_id, self.value.id)
        return self.value

    async def resolve(self, **kwargs: object) -> ReviewDetail:
        self.resolutions.append(kwargs)
        return self.value


@pytest.mark.asyncio
async def test_non_utf8_review_form_redirects_instead_of_crashing() -> None:
    """Regression: a malformed body must not surface as an unhandled 500."""
    account_id = uuid4()
    review_id = uuid4()
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    reviews = Reviews(detail(account_id, review_id))
    application = create_app()
    application.dependency_overrides[get_web_session_manager] = lambda: manager
    application.dependency_overrides[get_review_service] = lambda: reviews
    transport = httpx.ASGITransport(app=application)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://agent.example",
        follow_redirects=False,
    ) as client:
        session = manager.issue(
            account_id,
            admin_home_account_id="admin-account",
            admin_tenant_id=None,
        )
        client.cookies.set(manager.cookie_name, session)
        response = await client.post(
            f"/reviews/{review_id}/resolve",
            content=b"choice=\xff\xfe",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 303
    assert reviews.resolutions == []


@pytest.mark.asyncio
async def test_review_pages_require_session_and_post_requires_bound_csrf() -> None:
    account_id = uuid4()
    review_id = uuid4()
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    reviews = Reviews(detail(account_id, review_id))
    application = create_app()
    application.dependency_overrides[get_web_session_manager] = lambda: manager
    application.dependency_overrides[get_review_service] = lambda: reviews
    transport = httpx.ASGITransport(app=application)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://agent.example",
        follow_redirects=False,
    ) as client:
        unauthenticated = await client.get(f"/reviews/{review_id}")
        session = manager.issue(
            account_id,
            admin_home_account_id="admin-account",
            admin_tenant_id=None,
        )
        client.cookies.set(manager.cookie_name, session)
        page = await client.get(f"/reviews/{review_id}")
        rejected = await client.post(
            f"/reviews/{review_id}/resolve",
            content=(
                "choice=Europe%2FLondon&expected_version=1&csrf_token=incorrect"
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        csrf = manager.csrf_token(
            session_token=session,
            review_id=review_id,
            version=1,
        )
        accepted = await client.post(
            f"/reviews/{review_id}/resolve",
            content=(
                "choice=Europe%2FLondon&expected_version=1&csrf_token=" + csrf
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert unauthenticated.status_code == 303
    assert unauthenticated.headers["location"].startswith("/auth/login?return_to=")
    assert page.status_code == 200
    assert "Extracted event" in page.text
    assert "Time evidence" in page.text
    assert "Field differences" in page.text
    assert "Side-effect preview" in page.text
    assert "Open original email" in page.text
    assert "<script>" not in page.text
    assert "candidate@example.test" not in page.text
    assert "secret.example" not in page.text
    assert "ACTION_LINK_01" in page.text
    assert "token=" not in page.text
    assert rejected.status_code == 403
    assert accepted.status_code == 303
    assert reviews.resolutions == [
        {
            "account_id": account_id,
            "review_id": review_id,
            "choice": "Europe/London",
            "override_value": None,
            "expected_version": 1,
        }
    ]
