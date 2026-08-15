"""Workflow telemetry emitted at the persistence decorator boundary.

Every graph node reports its stage through ``WorkflowPersistence`` before it
runs, so wrapping that port yields stage-level durations, final outcomes, and
LLM usage without touching a single node. The wrapper never changes
persistence behavior; metrics are emitted only after the inner call succeeds.
"""

from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from uuid import UUID

from recruitment_agent.graph.contracts import (
    ExtractionAudit,
    ProcessingRun,
    ProcessingRunStatus,
    ReviewDecision,
    ReviewItem,
    WorkflowExtractionResult,
    WorkflowSourceEmail,
    WorkflowStage,
)
from recruitment_agent.graph.ports import WorkflowPersistence
from recruitment_agent.observability.metrics import MetricEmitter

_MAX_TIMING_ENTRIES = 256


@dataclass
class _RunTiming:
    started_at: float
    last_stage: str
    last_mark: float
    started_in_process: bool = field(default=True)


class MetricsWorkflowPersistence:
    """Emit stage timing and outcome metrics around any workflow persistence."""

    def __init__(
        self,
        inner: WorkflowPersistence,
        *,
        emitter: MetricEmitter | None = None,
    ) -> None:
        self._inner = inner
        self._emitter = emitter or MetricEmitter()
        self._runs: dict[UUID, _RunTiming] = {}

    def _observe_stage(
        self,
        processing_run_id: UUID,
        stage: WorkflowStage,
        *,
        started_in_process: bool,
    ) -> None:
        now = perf_counter()
        timing = self._runs.get(processing_run_id)
        if timing is None:
            if len(self._runs) >= _MAX_TIMING_ENTRIES:
                oldest = min(self._runs, key=lambda key: self._runs[key].last_mark)
                self._runs.pop(oldest, None)
            # A resumed workflow re-enters mid-graph in a fresh process; time
            # only what this process observed instead of inventing a duration.
            self._runs[processing_run_id] = _RunTiming(
                started_at=now,
                last_stage=stage.value,
                last_mark=now,
                started_in_process=started_in_process,
            )
            return
        elapsed_ms = (now - timing.last_mark) * 1000
        self._emitter.emit(
            "workflow_stage_duration_ms",
            elapsed_ms,
            {"stage": timing.last_stage},
        )
        timing.last_stage = stage.value
        timing.last_mark = now

    async def load_source_email(self, source_email_id: UUID) -> WorkflowSourceEmail:
        return await self._inner.load_source_email(source_email_id)

    async def start_run(self, run: ProcessingRun) -> None:
        await self._inner.start_run(run)
        self._observe_stage(run.id, run.current_stage, started_in_process=True)

    async def get_run_status(
        self,
        processing_run_id: UUID,
    ) -> ProcessingRunStatus | None:
        return await self._inner.get_run_status(processing_run_id)

    async def mark_source_needs_review(self, source_email_id: UUID) -> None:
        await self._inner.mark_source_needs_review(source_email_id)

    async def advance_run(
        self,
        *,
        processing_run_id: UUID,
        stage: WorkflowStage,
        status: ProcessingRunStatus = ProcessingRunStatus.RUNNING,
    ) -> None:
        await self._inner.advance_run(
            processing_run_id=processing_run_id,
            stage=stage,
            status=status,
        )
        self._observe_stage(processing_run_id, stage, started_in_process=False)

    async def record_extraction(
        self,
        audit: ExtractionAudit,
    ) -> WorkflowExtractionResult:
        stored = await self._inner.record_extraction(audit)
        usage = audit.result.usage
        if usage is not None:
            dimensions = {"prompt_version": audit.result.prompt_version}
            self._emitter.emit(
                "llm_extraction_latency_ms",
                float(usage.latency_ms),
                dimensions,
            )
            if usage.prompt_tokens is not None:
                self._emitter.emit("llm_prompt_tokens", float(usage.prompt_tokens), dimensions)
            if usage.completion_tokens is not None:
                self._emitter.emit(
                    "llm_completion_tokens",
                    float(usage.completion_tokens),
                    dimensions,
                )
        return stored

    async def open_review(self, item: ReviewItem) -> ReviewItem:
        opened = await self._inner.open_review(item)
        self._emitter.emit(
            "workflow_review_opened",
            1.0,
            {"review_type": item.request.review_type.value},
        )
        return opened

    async def resolve_review(
        self,
        *,
        review_id: UUID,
        decision: ReviewDecision,
        resolved_at: datetime,
    ) -> None:
        await self._inner.resolve_review(
            review_id=review_id,
            decision=decision,
            resolved_at=resolved_at,
        )

    async def finalize_run(
        self,
        *,
        processing_run_id: UUID,
        source_email_id: UUID,
        stage: WorkflowStage,
        status: ProcessingRunStatus,
        finished_at: datetime,
        error_code: str | None = None,
        error_detail_sanitized: str | None = None,
    ) -> None:
        await self._inner.finalize_run(
            processing_run_id=processing_run_id,
            source_email_id=source_email_id,
            stage=stage,
            status=status,
            finished_at=finished_at,
            error_code=error_code,
            error_detail_sanitized=error_detail_sanitized,
        )
        now = perf_counter()
        timing = self._runs.pop(processing_run_id, None)
        dimensions = {"status": status.value, "stage": stage.value}
        self._emitter.emit("workflow_run_finalized", 1.0, dimensions)
        if timing is None:
            return
        self._emitter.emit(
            "workflow_stage_duration_ms",
            (now - timing.last_mark) * 1000,
            {"stage": timing.last_stage},
        )
        if timing.started_in_process:
            self._emitter.emit(
                "workflow_run_duration_ms",
                (now - timing.started_at) * 1000,
                {"status": status.value},
            )
