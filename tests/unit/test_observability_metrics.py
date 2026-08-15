"""Metric emitter privacy and workflow persistence telemetry decoration."""

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from recruitment_agent.extraction.models import (
    ExtractionUsage,
    ExtractionValidationResult,
    ExtractionValidationStatus,
    RecruitmentExtraction,
)
from recruitment_agent.graph.contracts import (
    ExtractionAudit,
    ProcessingRun,
    ProcessingRunStatus,
    ReviewItem,
    ReviewRequest,
    ReviewType,
    WorkflowExtractionResult,
    WorkflowStage,
)
from recruitment_agent.observability.metrics import METRIC_LOG_PREFIX, MetricEmitter
from recruitment_agent.observability.workflow import (
    _MAX_TIMING_ENTRIES,
    MetricsWorkflowPersistence,
)

_FIXTURE = json.loads(Path("tests/fixtures/extraction/offer.json").read_text(encoding="utf-8"))


def test_metric_emitter_writes_parseable_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.metrics.payload")
    caplog.set_level(logging.INFO, logger=logger.name)
    MetricEmitter(logger).emit(
        "workflow_stage_duration_ms",
        12.5,
        {"stage": "normalize_email"},
    )

    message = caplog.records[-1].getMessage()
    assert message.startswith(f"{METRIC_LOG_PREFIX} ")
    payload = json.loads(message[len(METRIC_LOG_PREFIX) + 1 :])
    assert payload == {
        "dimensions": {"stage": "normalize_email"},
        "metric": "workflow_stage_duration_ms",
        "value": 12.5,
    }


def test_metric_emitter_redacts_unsafe_dimension_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.metrics.redact")
    caplog.set_level(logging.INFO, logger=logger.name)
    MetricEmitter(logger).emit(
        "workflow_run_finalized",
        1.0,
        {"status": "评审 with spaces and secrets"},
    )

    message = caplog.records[-1].getMessage()
    payload = json.loads(message[len(METRIC_LOG_PREFIX) + 1 :])
    assert payload["dimensions"] == {"status": "redacted"}
    assert "secrets" not in message


def test_metric_emitter_rejects_invalid_names() -> None:
    emitter = MetricEmitter(logging.getLogger("test.metrics.reject"))
    with pytest.raises(ValueError, match="metric name"):
        emitter.emit("Bad-Name", 1.0)
    with pytest.raises(ValueError, match="dimension keys"):
        emitter.emit("valid_name", 1.0, {"Bad Key": "value"})


class RecordingEmitter(MetricEmitter):
    def __init__(self) -> None:
        super().__init__(logging.getLogger("test.metrics.recording"))
        self.events: list[tuple[str, float, dict[str, str]]] = []

    def emit(
        self,
        name: str,
        value: float,
        dimensions: Mapping[str, str] | None = None,
    ) -> None:
        self.events.append((name, value, dict(dimensions or {})))

    def names(self) -> list[str]:
        return [name for name, _, _ in self.events]


class FakeInnerPersistence:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start_run(self, run: ProcessingRun) -> None:
        del run
        self.calls.append("start_run")

    async def advance_run(
        self,
        *,
        processing_run_id: object,
        stage: WorkflowStage,
        status: ProcessingRunStatus = ProcessingRunStatus.RUNNING,
    ) -> None:
        del processing_run_id, stage, status
        self.calls.append("advance_run")

    async def record_extraction(
        self,
        audit: ExtractionAudit,
    ) -> WorkflowExtractionResult:
        self.calls.append("record_extraction")
        return audit.result

    async def open_review(self, item: ReviewItem) -> ReviewItem:
        self.calls.append("open_review")
        return item

    async def finalize_run(
        self,
        *,
        processing_run_id: object,
        source_email_id: object,
        stage: WorkflowStage,
        status: ProcessingRunStatus,
        finished_at: datetime,
        error_code: str | None = None,
        error_detail_sanitized: str | None = None,
    ) -> None:
        del processing_run_id, source_email_id, stage, status
        del finished_at, error_code, error_detail_sanitized
        self.calls.append("finalize_run")


def _extraction_result(usage: ExtractionUsage | None) -> WorkflowExtractionResult:
    return WorkflowExtractionResult(
        extraction=RecruitmentExtraction.model_validate(_FIXTURE["response"]),
        validation=ExtractionValidationResult(
            status=ExtractionValidationStatus.VALID,
            issues=(),
        ),
        prompt_version="recruitment-extraction-v2",
        company=None,
        role=None,
        company_resolution_audit_id=None,
        usage=usage,
    )


@pytest.mark.asyncio
async def test_stage_and_run_metrics_are_emitted_for_a_full_run() -> None:
    emitter = RecordingEmitter()
    inner = FakeInnerPersistence()
    persistence = MetricsWorkflowPersistence(inner, emitter=emitter)  # type: ignore[arg-type]
    run_id = uuid4()
    source_id = uuid4()
    started_at = datetime(2026, 8, 15, 12, tzinfo=UTC)

    await persistence.start_run(
        ProcessingRun(
            id=run_id,
            source_email_id=source_id,
            graph_thread_id=str(run_id),
            current_stage=WorkflowStage.LOAD_SOURCE_EMAIL,
            status=ProcessingRunStatus.RUNNING,
            prompt_version="recruitment-extraction-v2",
            model_deployment=None,
            started_at=started_at,
        )
    )
    await persistence.advance_run(
        processing_run_id=run_id,
        stage=WorkflowStage.NORMALIZE_EMAIL,
    )
    await persistence.advance_run(
        processing_run_id=run_id,
        stage=WorkflowStage.PREFILTER_RECRUITMENT,
    )
    await persistence.finalize_run(
        processing_run_id=run_id,
        source_email_id=source_id,
        stage=WorkflowStage.FINALIZE_PROCESSING,
        status=ProcessingRunStatus.COMPLETED,
        finished_at=started_at,
    )

    names = emitter.names()
    assert names.count("workflow_stage_duration_ms") == 3
    stage_dimensions = [
        dimensions["stage"]
        for name, _, dimensions in emitter.events
        if name == "workflow_stage_duration_ms"
    ]
    assert stage_dimensions == [
        "load_source_email",
        "normalize_email",
        "prefilter_recruitment",
    ]
    finalized = [event for event in emitter.events if event[0] == "workflow_run_finalized"]
    assert finalized == [
        (
            "workflow_run_finalized",
            1.0,
            {"status": "completed", "stage": "finalize_processing"},
        )
    ]
    durations = [event for event in emitter.events if event[0] == "workflow_run_duration_ms"]
    assert len(durations) == 1
    assert durations[0][2] == {"status": "completed"}
    assert inner.calls == ["start_run", "advance_run", "advance_run", "finalize_run"]


@pytest.mark.asyncio
async def test_finalize_without_observed_start_skips_run_duration() -> None:
    emitter = RecordingEmitter()
    persistence = MetricsWorkflowPersistence(
        FakeInnerPersistence(),  # type: ignore[arg-type]
        emitter=emitter,
    )
    await persistence.finalize_run(
        processing_run_id=uuid4(),
        source_email_id=uuid4(),
        stage=WorkflowStage.FINALIZE_PROCESSING,
        status=ProcessingRunStatus.FAILED,
        finished_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
    )

    names = emitter.names()
    assert "workflow_run_finalized" in names
    assert "workflow_run_duration_ms" not in names
    assert "workflow_stage_duration_ms" not in names


@pytest.mark.asyncio
async def test_llm_usage_metrics_follow_record_extraction() -> None:
    emitter = RecordingEmitter()
    persistence = MetricsWorkflowPersistence(
        FakeInnerPersistence(),  # type: ignore[arg-type]
        emitter=emitter,
    )
    usage = ExtractionUsage(prompt_tokens=812, completion_tokens=96, latency_ms=1450)
    audit = ExtractionAudit.create(
        processing_run_id=uuid4(),
        source_email_id=uuid4(),
        result=_extraction_result(usage),
        created_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
    )
    await persistence.record_extraction(audit)

    assert (
        "llm_extraction_latency_ms",
        1450.0,
        {"prompt_version": "recruitment-extraction-v2"},
    ) in emitter.events
    assert (
        "llm_prompt_tokens",
        812.0,
        {"prompt_version": "recruitment-extraction-v2"},
    ) in emitter.events
    assert (
        "llm_completion_tokens",
        96.0,
        {"prompt_version": "recruitment-extraction-v2"},
    ) in emitter.events


@pytest.mark.asyncio
async def test_record_extraction_without_usage_emits_no_llm_metrics() -> None:
    emitter = RecordingEmitter()
    persistence = MetricsWorkflowPersistence(
        FakeInnerPersistence(),  # type: ignore[arg-type]
        emitter=emitter,
    )
    audit = ExtractionAudit.create(
        processing_run_id=uuid4(),
        source_email_id=uuid4(),
        result=_extraction_result(None),
        created_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
    )
    await persistence.record_extraction(audit)

    assert emitter.events == []


@pytest.mark.asyncio
async def test_open_review_emits_review_type_metric() -> None:
    emitter = RecordingEmitter()
    persistence = MetricsWorkflowPersistence(
        FakeInnerPersistence(),  # type: ignore[arg-type]
        emitter=emitter,
    )
    item = ReviewItem.create(
        processing_run_id=uuid4(),
        request=ReviewRequest(
            review_type=ReviewType.TIMEZONE_AMBIGUITY,
            reason="timezone_ambiguity",
            question="Bind the wall clock to a timezone.",
            allowed_choices=("Europe/London", "ignore"),
        ),
        created_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
    )
    await persistence.open_review(item)

    assert (
        "workflow_review_opened",
        1.0,
        {"review_type": "TIMEZONE_AMBIGUITY"},
    ) in emitter.events


@pytest.mark.asyncio
async def test_unfinalized_run_timings_are_bounded() -> None:
    persistence = MetricsWorkflowPersistence(
        FakeInnerPersistence(),  # type: ignore[arg-type]
        emitter=RecordingEmitter(),
    )
    started_at = datetime(2026, 8, 15, 12, tzinfo=UTC)
    for _ in range(_MAX_TIMING_ENTRIES + 5):
        run_id = uuid4()
        await persistence.start_run(
            ProcessingRun(
                id=run_id,
                source_email_id=uuid4(),
                graph_thread_id=str(run_id),
                current_stage=WorkflowStage.LOAD_SOURCE_EMAIL,
                status=ProcessingRunStatus.RUNNING,
                prompt_version="recruitment-extraction-v2",
                model_deployment=None,
                started_at=started_at,
            )
        )

    assert len(persistence._runs) == _MAX_TIMING_ENTRIES
