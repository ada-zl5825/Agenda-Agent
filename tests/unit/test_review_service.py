import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from recruitment_agent.application.errors import (
    ReviewAccessDeniedError,
    ReviewConflictError,
)
from recruitment_agent.application.reviews import ReviewService
from recruitment_agent.graph.contracts import ReviewDecision
from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem


def detail(account_id: UUID) -> ReviewDetail:
    return ReviewDetail(
        id=uuid4(),
        account_id=account_id,
        processing_run_id=uuid4(),
        source_email_id=uuid4(),
        review_type="TIMEZONE_AMBIGUITY",
        status="open",
        reason="TIMEZONE_MISSING",
        question="Which timezone applies?",
        allowed_choices=("Europe/London", "other"),
        version=1,
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
        resolved_at=None,
        resolution=None,
        run_status="needs_review",
        source={},
        application={},
        extraction={},
        validation_findings=(),
        current_values={},
        proposed_values={},
        candidates=(),
        secure_links=(),
        side_effects=(),
    )


def queue_item(
    value: ReviewDetail,
    *,
    item_id: UUID | None = None,
    orphaned: bool = False,
) -> ReviewQueueItem:
    return ReviewQueueItem(
        id=item_id or value.id,
        source_email_id=value.source_email_id,
        review_type=value.review_type,
        reason=value.reason,
        created_at=value.created_at,
        company=None,
        role=None,
        subject=None,
        event_type=None,
        source_time_text=None,
        orphaned=orphaned,
    )


class Store:
    def __init__(self, value: ReviewDetail) -> None:
        self.value = value
        self.open_items: tuple[ReviewQueueItem, ...] = ()

    async def list_open(self, *, account_id: UUID) -> tuple[ReviewQueueItem, ...]:
        del account_id
        return self.open_items

    async def get_detail(
        self,
        *,
        account_id: UUID,
        review_id: UUID,
    ) -> ReviewDetail | None:
        del account_id
        return self.value if review_id == self.value.id else None


class Resume:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.decision: ReviewDecision | None = None
        self.calls = 0

    async def __call__(self, **kwargs: object) -> object:
        decision = kwargs["decision"]
        assert isinstance(decision, ReviewDecision)
        self.decision = decision
        self.calls += 1
        self.store.value = replace(
            self.store.value,
            status="resolved",
            version=2,
            resolution=decision.model_dump(mode="json"),
        )
        return object()


@pytest.mark.asyncio
async def test_review_service_validates_choice_before_resuming_workflow() -> None:
    account_id = uuid4()
    store = Store(detail(account_id))
    resume = Resume(store)
    service = ReviewService(store=store, resumer=resume)

    with pytest.raises(ReviewConflictError):
        await service.resolve(
            account_id=account_id,
            review_id=store.value.id,
            choice="attacker-choice",
            override_value=None,
            expected_version=1,
        )
    resolved = await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )

    assert resume.decision == ReviewDecision(
        choice="Europe/London",
        expected_version=1,
    )
    assert resolved.status == "resolved"


@pytest.mark.asyncio
async def test_duplicate_submit_of_same_decision_resumes_a_stranded_run() -> None:
    """Regression: a double click cancelled the first resolve mid-resume in
    production, leaving the review resolved but the run stuck. The identical
    resubmit must recover the run instead of bouncing to an error page."""
    account_id = uuid4()
    store = Store(detail(account_id))
    resume = Resume(store)
    service = ReviewService(store=store, resumer=resume)

    await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )
    # run_status stays "needs_review" and no open review exists: stranded run.
    recovered = await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )

    assert resume.calls == 2
    assert recovered.status == "resolved"


@pytest.mark.asyncio
async def test_duplicate_submit_resumes_when_the_queue_only_shows_an_orphan() -> None:
    """Regression: list_open() includes orphaned 处理中断 cards for a stranded
    run. Treating those as a follow-up review would skip recovery."""
    account_id = uuid4()
    store = Store(detail(account_id))
    resume = Resume(store)
    service = ReviewService(store=store, resumer=resume)

    await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )
    store.open_items = (queue_item(store.value, item_id=uuid4(), orphaned=True),)
    recovered = await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )

    assert resume.calls == 2
    assert recovered.status == "resolved"


@pytest.mark.asyncio
async def test_concurrent_resolves_share_one_resume() -> None:
    account_id = uuid4()
    store = Store(detail(account_id))
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowResume:
        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, **kwargs: object) -> object:
            del kwargs
            self.calls += 1
            started.set()
            await release.wait()
            return object()

    slow = SlowResume()
    service = ReviewService(store=store, resumer=slow)
    first = asyncio.create_task(
        service.resolve(
            account_id=account_id,
            review_id=store.value.id,
            choice="Europe/London",
            override_value=None,
            expected_version=1,
        )
    )
    await started.wait()
    second = asyncio.create_task(
        service.resolve(
            account_id=account_id,
            review_id=store.value.id,
            choice="Europe/London",
            override_value=None,
            expected_version=1,
        )
    )
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)

    assert slow.calls == 1


@pytest.mark.asyncio
async def test_duplicate_submit_does_not_resume_when_workflow_moved_on() -> None:
    account_id = uuid4()
    store = Store(detail(account_id))
    resume = Resume(store)
    service = ReviewService(store=store, resumer=resume)

    await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )
    # A follow-up review for the same email is already open.
    store.open_items = (queue_item(store.value, item_id=uuid4()),)
    recovered = await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )

    assert resume.calls == 1
    assert recovered.status == "resolved"


@pytest.mark.asyncio
async def test_duplicate_submit_does_not_resume_a_finalized_run() -> None:
    account_id = uuid4()
    store = Store(detail(account_id))
    resume = Resume(store)
    service = ReviewService(store=store, resumer=resume)

    await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )
    store.value = replace(store.value, run_status="completed")
    recovered = await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )

    assert resume.calls == 1
    assert recovered.status == "resolved"


@pytest.mark.asyncio
async def test_resubmit_with_a_different_decision_stays_a_conflict() -> None:
    account_id = uuid4()
    store = Store(detail(account_id))
    resume = Resume(store)
    service = ReviewService(store=store, resumer=resume)

    await service.resolve(
        account_id=account_id,
        review_id=store.value.id,
        choice="Europe/London",
        override_value=None,
        expected_version=1,
    )
    with pytest.raises(ReviewConflictError):
        await service.resolve(
            account_id=account_id,
            review_id=store.value.id,
            choice="other",
            override_value="Asia/Shanghai",
            expected_version=1,
        )

    assert resume.calls == 1


@pytest.mark.asyncio
async def test_cancelled_resolve_request_lets_the_resume_finish() -> None:
    """Regression: the browser cancelling the POST must not strand the
    workflow between the review resolution and its side effects."""
    account_id = uuid4()
    store = Store(detail(account_id))

    class SlowResume:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.finished = False

        async def __call__(self, **kwargs: object) -> object:
            del kwargs
            self.started.set()
            await asyncio.sleep(0.05)
            self.finished = True
            return object()

    slow = SlowResume()
    service = ReviewService(store=store, resumer=slow)

    task = asyncio.create_task(
        service.resolve(
            account_id=account_id,
            review_id=store.value.id,
            choice="Europe/London",
            override_value=None,
            expected_version=1,
        )
    )
    await slow.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.1)

    assert slow.finished


@pytest.mark.asyncio
async def test_review_service_rejects_a_detail_owned_by_another_account() -> None:
    account_id = uuid4()
    store = Store(detail(uuid4()))
    service = ReviewService(store=store, resumer=Resume(store))

    with pytest.raises(ReviewAccessDeniedError):
        await service.get_detail(account_id=account_id, review_id=store.value.id)
