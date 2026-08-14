from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from recruitment_agent.api.app import create_app
from recruitment_agent.api.dependencies import get_review_service, get_web_session_manager
from recruitment_agent.application.errors import TimeEvidenceUnresolvedError
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
        self.fail_with: Exception | None = None
        self.next_review_id: UUID | None = None

    async def list_open(self, *, account_id: UUID) -> tuple[ReviewQueueItem, ...]:
        assert account_id == self.value.account_id
        return (
            ReviewQueueItem(
                id=self.value.id,
                source_email_id=self.value.source_email_id,
                review_type=self.value.review_type,
                reason=self.value.reason,
                created_at=self.value.created_at,
                company="Example",
                role="Engineer",
                subject="Interview invitation",
                event_type="interview",
                source_time_text="Friday at 10",
            ),
        )

    async def get_detail(self, *, account_id: UUID, review_id: UUID) -> ReviewDetail:
        assert (account_id, review_id) == (self.value.account_id, self.value.id)
        return self.value

    async def resolve(self, **kwargs: object) -> ReviewDetail:
        self.resolutions.append(kwargs)
        if self.fail_with is not None:
            raise self.fail_with
        return self.value

    async def next_open_for_source(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        excluding_review_id: UUID,
    ) -> UUID | None:
        del account_id, source_email_id, excluding_review_id
        return self.next_review_id


@pytest.mark.asyncio
async def test_workflow_failure_after_resolve_redirects_with_error_code() -> None:
    account_id = uuid4()
    review_id = uuid4()
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    reviews = Reviews(detail(account_id, review_id))
    reviews.fail_with = TimeEvidenceUnresolvedError("event_datetime_unresolved")
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
        csrf = manager.csrf_token(
            session_token=session,
            review_id=review_id,
            version=1,
        )
        response = await client.post(
            f"/reviews/{review_id}/resolve",
            content=(
                "choice=Europe%2FLondon&expected_version=1&csrf_token=" + csrf
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 303
    assert "error=EVENT_DATETIME_UNRESOLVED" in response.headers["location"]


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
    assert "抽出的事件" in page.text
    assert "时间证据" in page.text
    assert "字段差异" in page.text or "现有记录 vs 建议" in page.text
    assert "副作用预览" in page.text
    assert "Agenda Agent" in page.text
    assert "打开原邮件" in page.text
    assert "确认时区" in page.text
    assert "Example" in page.text
    assert "<script>" not in page.text
    assert "candidate@example.test" not in page.text
    assert "secret.example" not in page.text
    assert "ACTION_LINK_01" in page.text
    assert "token=" not in page.text
    assert rejected.status_code == 403
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/reviews"
    assert reviews.resolutions == [
        {
            "account_id": account_id,
            "review_id": review_id,
            "choice": "Europe/London",
            "override_value": None,
            "expected_version": 1,
            "clock_override": None,
        }
    ]


@pytest.mark.asyncio
async def test_resolve_continues_to_the_next_review_for_the_same_email() -> None:
    account_id = uuid4()
    review_id = uuid4()
    next_id = uuid4()
    manager = WebSessionManager(key=b"s" * 32, clock=Clock())
    reviews = Reviews(detail(account_id, review_id))
    reviews.next_review_id = next_id
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
        queue = await client.get("/reviews")
        csrf = manager.csrf_token(
            session_token=session,
            review_id=review_id,
            version=1,
        )
        response = await client.post(
            f"/reviews/{review_id}/resolve",
            content=("choice=Europe%2FLondon&expected_version=1&csrf_token=" + csrf),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert "Example · Engineer" in queue.text
    assert "确认时区" in queue.text
    assert "TIMEZONE_AMBIGUITY" not in queue.text
    assert response.status_code == 303
    assert response.headers["location"] == f"/reviews/{next_id}"
