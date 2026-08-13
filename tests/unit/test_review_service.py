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
from recruitment_agent.reviews.models import ReviewDetail


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


class Store:
    def __init__(self, value: ReviewDetail) -> None:
        self.value = value

    async def list_open(self, *, account_id: UUID) -> tuple[object, ...]:
        del account_id
        return ()

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

    async def __call__(self, **kwargs: object) -> object:
        decision = kwargs["decision"]
        assert isinstance(decision, ReviewDecision)
        self.decision = decision
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
    with pytest.raises(ReviewConflictError):
        await service.resolve(
            account_id=account_id,
            review_id=store.value.id,
            choice="Europe/London",
            override_value=None,
            expected_version=1,
        )


@pytest.mark.asyncio
async def test_review_service_rejects_a_detail_owned_by_another_account() -> None:
    account_id = uuid4()
    store = Store(detail(uuid4()))
    service = ReviewService(store=store, resumer=Resume(store))

    with pytest.raises(ReviewAccessDeniedError):
        await service.get_detail(account_id=account_id, review_id=store.value.id)
