"""Authenticated, typed and idempotent graphical Review operations."""

from typing import Protocol
from uuid import UUID

from recruitment_agent.application.errors import (
    ReviewAccessDeniedError,
    ReviewConflictError,
    ReviewNotFoundError,
)
from recruitment_agent.graph.contracts import ReviewDecision, ReviewRequest, ReviewType
from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem


class ReviewStore(Protocol):
    async def list_open(self, *, account_id: UUID) -> tuple[ReviewQueueItem, ...]: ...

    async def get_detail(self, *, account_id: UUID, review_id: UUID) -> ReviewDetail | None: ...


class ReviewWorkflowResumer(Protocol):
    async def __call__(
        self,
        *,
        processing_run_id: UUID,
        source_email_id: UUID,
        decision: ReviewDecision,
    ) -> object: ...


class ReviewService:
    def __init__(self, *, store: ReviewStore, resumer: ReviewWorkflowResumer) -> None:
        self._store = store
        self._resumer = resumer

    async def list_open(self, *, account_id: UUID) -> tuple[ReviewQueueItem, ...]:
        return await self._store.list_open(account_id=account_id)

    async def get_detail(self, *, account_id: UUID, review_id: UUID) -> ReviewDetail:
        detail = await self._store.get_detail(account_id=account_id, review_id=review_id)
        if detail is None:
            raise ReviewNotFoundError("review does not exist for this account")
        if detail.account_id != account_id:
            raise ReviewAccessDeniedError("review belongs to another account")
        return detail

    async def next_open_for_source(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        excluding_review_id: UUID,
    ) -> UUID | None:
        for item in await self.list_open(account_id=account_id):
            if item.source_email_id == source_email_id and item.id != excluding_review_id:
                return item.id
        return None

    async def resolve(
        self,
        *,
        account_id: UUID,
        review_id: UUID,
        choice: str,
        override_value: str | None,
        expected_version: int,
        clock_override: str | None = None,
    ) -> ReviewDetail:
        detail = await self.get_detail(account_id=account_id, review_id=review_id)
        if detail.status != "open" or detail.version != expected_version:
            raise ReviewConflictError("review is stale or already resolved")
        request = ReviewRequest(
            review_type=ReviewType(detail.review_type),
            reason=detail.reason,
            question=detail.question,
            allowed_choices=detail.allowed_choices,
        )
        try:
            decision = ReviewDecision(
                choice=choice,
                override_value=override_value,
                clock_override=clock_override,
                expected_version=expected_version,
            )
            from recruitment_agent.graph.contracts import validate_review_decision

            decision = validate_review_decision(request, decision.model_dump(mode="json"))
        except ValueError as exc:
            raise ReviewConflictError("review decision is invalid") from exc
        await self._resumer(
            processing_run_id=detail.processing_run_id,
            source_email_id=detail.source_email_id,
            decision=decision,
        )
        return await self.get_detail(account_id=account_id, review_id=review_id)
