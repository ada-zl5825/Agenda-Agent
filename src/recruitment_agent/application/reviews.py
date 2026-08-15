"""Authenticated, typed and idempotent graphical Review operations."""

import asyncio
import logging
from collections.abc import Callable
from functools import partial
from typing import Protocol
from uuid import UUID

from recruitment_agent.application.errors import (
    ReviewAccessDeniedError,
    ReviewConflictError,
    ReviewNotFoundError,
)
from recruitment_agent.graph.contracts import (
    ReviewDecision,
    ReviewRequest,
    ReviewType,
    validate_review_decision,
)
from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem

LOGGER = logging.getLogger(__name__)

_FINAL_RUN_STATUSES = frozenset({"completed", "ignored", "failed"})


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


def _log_background_resume(
    task: "asyncio.Task[object]",
    *,
    processing_run_id: UUID,
) -> None:
    if task.cancelled():
        LOGGER.warning(
            "review_resume_background_cancelled run_id=%s",
            processing_run_id,
        )
        return
    exc = task.exception()
    if exc is not None:
        LOGGER.error(
            "review_resume_background_failed:%s run_id=%s",
            type(exc).__name__,
            processing_run_id,
            extra={"error_type": type(exc).__name__},
        )


class ReviewService:
    def __init__(self, *, store: ReviewStore, resumer: ReviewWorkflowResumer) -> None:
        self._store = store
        self._resumer = resumer
        self._resume_lock = asyncio.Lock()
        self._resume_tasks: dict[UUID, asyncio.Task[object]] = {}

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
            decision = validate_review_decision(request, decision.model_dump(mode="json"))
        except ValueError as exc:
            raise ReviewConflictError("review decision is invalid") from exc
        if detail.status != "open":
            return await self._recover_duplicate(
                account_id=account_id,
                detail=detail,
                decision=decision,
            )
        if detail.version != expected_version:
            raise ReviewConflictError("review is stale or already resolved")
        await self._resume_shielded(
            processing_run_id=detail.processing_run_id,
            source_email_id=detail.source_email_id,
            decision=decision,
        )
        return await self.get_detail(account_id=account_id, review_id=review_id)

    async def _recover_duplicate(
        self,
        *,
        account_id: UUID,
        detail: ReviewDetail,
        decision: ReviewDecision,
    ) -> ReviewDetail:
        """Make a repeated submit of the same decision idempotent.

        A double click or a client disconnect can cancel the first resolve
        request after the review row was resolved but before the workflow
        finished its side effects. Re-raising a conflict there strands the run;
        instead the identical decision resumes the interrupted workflow.
        """
        if detail.status != "resolved" or detail.resolution != decision.model_dump(mode="json"):
            raise ReviewConflictError("review is stale or already resolved")
        for item in await self.list_open(account_id=account_id):
            if item.source_email_id == detail.source_email_id and not item.orphaned:
                # A real follow-up review is already open. An orphaned queue
                # card is the stranded-run state this recovery exists to fix.
                return detail
        if detail.run_status in _FINAL_RUN_STATUSES:
            return detail
        LOGGER.info(
            "review_resume_recovered_after_duplicate_submit run_id=%s",
            detail.processing_run_id,
        )
        await self._resume_shielded(
            processing_run_id=detail.processing_run_id,
            source_email_id=detail.source_email_id,
            decision=decision,
        )
        return await self.get_detail(account_id=account_id, review_id=detail.id)

    async def _resume_shielded(
        self,
        *,
        processing_run_id: UUID,
        source_email_id: UUID,
        decision: ReviewDecision,
    ) -> None:
        """Resume the workflow and keep it running if the HTTP request dies.

        The browser cancelling the POST (double submit, navigation, timeout)
        must not cancel the LangGraph resume between the review resolution and
        its calendar/domain side effects. Concurrent POSTs for the same run
        share one in-flight resume instead of issuing a second Command.
        """
        task = await self._coalesce_resume(
            processing_run_id=processing_run_id,
            source_email_id=source_email_id,
            decision=decision,
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done():
                callback: Callable[[asyncio.Task[object]], None] = partial(
                    _log_background_resume,
                    processing_run_id=processing_run_id,
                )
                task.add_done_callback(callback)
            raise

    async def _coalesce_resume(
        self,
        *,
        processing_run_id: UUID,
        source_email_id: UUID,
        decision: ReviewDecision,
    ) -> asyncio.Task[object]:
        async with self._resume_lock:
            existing = self._resume_tasks.get(processing_run_id)
            if existing is not None and not existing.done():
                return existing
            task = asyncio.ensure_future(
                self._resumer(
                    processing_run_id=processing_run_id,
                    source_email_id=source_email_id,
                    decision=decision,
                )
            )
            self._resume_tasks[processing_run_id] = task
            return task
