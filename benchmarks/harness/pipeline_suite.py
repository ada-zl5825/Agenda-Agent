"""L2 full-workflow correctness benchmark against real PostgreSQL.

Each case with an ``expected_domain`` block is driven through the production
LangGraph (real builder, nodes, PostgreSQL checkpointer, domain services, and
workflow persistence). Only two boundaries are replayed: transient email
preparation (the sanitized input comes from the dataset) and the LLM (the
recorded reference response). Final domain rows are asserted against golden
expectations and every checkpoint byte is scanned for URL material.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import cast
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from benchmarks.harness.extraction_suite import replay_model_for
from benchmarks.harness.loader import REPOSITORY_ROOT
from benchmarks.harness.models import (
    BenchmarkCase,
    BenchmarkDataset,
    ExpectedDomainOutcome,
    PipelineOutcome,
)
from benchmarks.harness.report import (
    PipelineAggregate,
    PipelineCaseResult,
    PipelineRunReport,
    RunMetadata,
)
from benchmarks.harness.scorers import percentile
from recruitment_agent.application.company_seed import CompanyCatalogSeeder
from recruitment_agent.application.domain_processing import RecruitmentDomainService
from recruitment_agent.application.entity_resolution import (
    RecruitmentEntityResolutionService,
)
from recruitment_agent.application.recruitment_extraction import (
    RecruitmentExtractionService,
)
from recruitment_agent.application.secure_email_processing import (
    SecureEmailPreparationService,
)
from recruitment_agent.domain.company import (
    CompanyAliasSeed,
    CompanyDomainSeed,
    CompanyEntityType,
    CompanySeed,
)
from recruitment_agent.domain.company_resolution import CompanyResolver
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_VERSION
from recruitment_agent.graph.activities import SecureRecruitmentWorkflowActivities
from recruitment_agent.graph.builder import build_recruitment_graph
from recruitment_agent.graph.context import RecruitmentGraphContext
from recruitment_agent.graph.contracts import (
    ExtractionAudit,
    ProcessingRun,
    ProcessingRunStatus,
    ReviewDecision,
    ReviewItem,
    SafePreparedEmail,
    WorkflowExtractionResult,
    WorkflowSourceEmail,
    WorkflowStage,
)
from recruitment_agent.graph.ports import DisabledCalendarSync
from recruitment_agent.graph.postgres import open_postgres_checkpointer
from recruitment_agent.graph.runner import (
    RecruitmentWorkflowRunner,
    WorkflowStartRequest,
)
from recruitment_agent.links.models import ActionLinkType
from recruitment_agent.persistence.companies import SqlAlchemyCompanyRepository
from recruitment_agent.persistence.company_resolutions import (
    SqlAlchemyCompanyResolutionAuditRepository,
)
from recruitment_agent.persistence.domain_processing import (
    SqlAlchemyRecruitmentDomainStore,
)
from recruitment_agent.persistence.models import (
    ActionItemModel,
    ApplicationModel,
    MicrosoftConnectionModel,
    RecruitmentEventModel,
    ReviewItemModel,
    SecureLinkModel,
    SourceEmailModel,
)
from recruitment_agent.persistence.session import (
    create_database_engine,
    create_session_factory,
)
from recruitment_agent.persistence.workflow import SqlAlchemyWorkflowPersistence

BENCHMARK_ACCOUNT_ID = UUID("a7d55f80-92b8-4f6c-9f6f-0a2a3c1d9b01")
_CHECKPOINT_URL_PATTERNS = ("https://", "http://", "mailto:")
_PLACEHOLDER_LINK_CIPHERTEXT = b"benchmark-link-ciphertext"
_PLACEHOLDER_LINK_NONCE = b"benchmarknonce"
_PLACEHOLDER_LINK_KEY_VERSION = "benchmark"
_UNSAFE_ERROR_MARKERS = ("http://", "https://", "mailto:")


def placeholder_secure_link_rows(
    *,
    source_email_id: UUID,
    link_refs: tuple[str, ...],
) -> tuple[SecureLinkModel, ...]:
    """Encrypted-looking rows so persist can resolve ``ACTION_LINK_*`` refs.

    Replay never extracts real destinations; ciphertext contains no URL bytes.
    """
    return tuple(
        SecureLinkModel(
            id=uuid4(),
            source_email_id=source_email_id,
            ref=ref,
            link_type=ActionLinkType.GENERAL.value,
            domain="benchmark.example",
            encrypted_url=_PLACEHOLDER_LINK_CIPHERTEXT,
            nonce=_PLACEHOLDER_LINK_NONCE,
            encryption_key_version=_PLACEHOLDER_LINK_KEY_VERSION,
            display_text=ref,
        )
        for ref in link_refs
    )


def sanitized_workflow_failure(exc: BaseException) -> str:
    """Keep the exception type and a URL-free message for benchmark reports."""
    detail = str(exc).strip()
    lowered = detail.lower()
    if not detail or any(marker in lowered for marker in _UNSAFE_ERROR_MARKERS):
        return f"workflow raised {type(exc).__name__}"
    return f"workflow raised {type(exc).__name__}: {detail}"


class _FixedClock:
    """Deterministic clock so run audit timestamps are reproducible."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class ReplayPreparationActivities(SecureRecruitmentWorkflowActivities):
    """Run the production extraction and resolution path with injected preparation.

    The transient preparation pipeline (Graph fetch, link encryption,
    sanitization) is exercised by its own tests; this suite starts from the
    checkpoint-safe sanitized input recorded in the dataset. Placeholder
    ``secure_links`` rows are seeded so persist can resolve ``ACTION_LINK_*``
    refs without storing URL bytes.
    """

    def __init__(
        self,
        *,
        prepared: SafePreparedEmail,
        extraction_service: RecruitmentExtractionService,
        entity_resolution_service: RecruitmentEntityResolutionService,
    ) -> None:
        super().__init__(
            # prepare_email is overridden, so the parent never touches this.
            preparation_service=cast(SecureEmailPreparationService, None),
            extraction_service=extraction_service,
            entity_resolution_service=entity_resolution_service,
        )
        self._prepared_static = prepared

    async def prepare_email(
        self,
        *,
        account_id: UUID,
        source_email_id: UUID,
        graph_message_id: str,
    ) -> SafePreparedEmail:
        del account_id, graph_message_id
        if source_email_id != self._prepared_static.source_email_id:
            raise ValueError("benchmark preparation identity mismatch")
        return self._prepared_static


class StageTimingPersistence:
    """Record wall-clock stage transitions without altering persistence behavior."""

    def __init__(self, inner: SqlAlchemyWorkflowPersistence) -> None:
        self._inner = inner
        self.stage_durations_ms: dict[str, float] = {}
        self._last_stage: str | None = None
        self._last_mark: float | None = None

    def _mark(self, stage: WorkflowStage) -> None:
        now = perf_counter()
        if self._last_stage is not None and self._last_mark is not None:
            elapsed = (now - self._last_mark) * 1000
            self.stage_durations_ms[self._last_stage] = (
                self.stage_durations_ms.get(self._last_stage, 0.0) + elapsed
            )
        self._last_stage = stage.value
        self._last_mark = now

    async def load_source_email(self, source_email_id: UUID) -> WorkflowSourceEmail:
        return await self._inner.load_source_email(source_email_id)

    async def start_run(self, run: ProcessingRun) -> None:
        self._mark(run.current_stage)
        await self._inner.start_run(run)

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
        self._mark(stage)
        await self._inner.advance_run(
            processing_run_id=processing_run_id,
            stage=stage,
            status=status,
        )

    async def record_extraction(
        self,
        audit: ExtractionAudit,
    ) -> WorkflowExtractionResult:
        return await self._inner.record_extraction(audit)

    async def open_review(self, item: ReviewItem) -> ReviewItem:
        return await self._inner.open_review(item)

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
        self._mark(stage)
        await self._inner.finalize_run(
            processing_run_id=processing_run_id,
            source_email_id=source_email_id,
            stage=stage,
            status=status,
            finished_at=finished_at,
            error_code=error_code,
            error_detail_sanitized=error_detail_sanitized,
        )


async def run_pipeline_suite(
    dataset: BenchmarkDataset,
    *,
    database_url: str | None = None,
    git_sha: str | None = None,
) -> PipelineRunReport:
    """Execute every pipeline case; owns a disposable PostgreSQL by default."""
    if database_url is not None:
        return await _run_with_database(dataset, database_url=database_url, git_sha=git_sha)
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        return await _run_with_database(
            dataset,
            database_url=postgres.get_connection_url(),
            git_sha=git_sha,
        )


async def _run_with_database(
    dataset: BenchmarkDataset,
    *,
    database_url: str,
    git_sha: str | None,
) -> PipelineRunReport:
    cases = tuple(case for case in dataset.cases if case.expected_domain is not None)
    if not cases:
        raise ValueError("dataset contains no pipeline cases")

    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        await _seed_companies(session_factory, dataset)
        async with session_factory.begin() as session:
            await session.merge(MicrosoftConnectionModel(id=BENCHMARK_ACCOUNT_ID))

        async with open_postgres_checkpointer(database_url) as checkpointer:
            results = [
                await _run_case(
                    case,
                    checkpointer=checkpointer,
                    session_factory=session_factory,
                )
                for case in cases
            ]
        violations = await _count_checkpoint_privacy_violations(session_factory)
    finally:
        await engine.dispose()

    meta = RunMetadata(
        suite="pipeline",
        mode="replay",
        run_at=datetime.now(UTC),
        git_sha=git_sha,
        prompt_version=RECRUITMENT_EXTRACTION_PROMPT_VERSION,
        model_deployment="benchmark-replay",
        dataset_name=dataset.manifest.dataset,
        dataset_version=dataset.manifest.version,
        dataset_case_count=dataset.manifest.case_count,
        executed_case_count=len(cases),
    )
    return PipelineRunReport(
        meta=meta,
        aggregate=_aggregate(tuple(results), violations),
        cases=tuple(results),
    )


async def _seed_companies(
    session_factory: async_sessionmaker[AsyncSession],
    dataset: BenchmarkDataset,
) -> None:
    seeds = tuple(
        CompanySeed(
            id=spec.company_id,
            canonical_name=spec.canonical_name,
            display_name=spec.display_name or spec.canonical_name,
            entity_type=CompanyEntityType.EMPLOYER,
            aliases=tuple(CompanyAliasSeed(alias=alias) for alias in spec.aliases),
            domains=tuple(CompanyDomainSeed(domain=domain) for domain in spec.domains),
        )
        for spec in dataset.companies
    )
    if seeds:
        await CompanyCatalogSeeder(SqlAlchemyCompanyRepository(session_factory)).seed(seeds)


async def _run_case(
    case: BenchmarkCase,
    *,
    checkpointer: BaseCheckpointSaver[str],
    session_factory: async_sessionmaker[AsyncSession],
) -> PipelineCaseResult:
    expected = case.expected_domain
    if expected is None:
        raise ValueError("pipeline case requires expected_domain")

    async with session_factory.begin() as session:
        await session.merge(
            SourceEmailModel(
                id=case.source_email_id,
                account_id=BENCHMARK_ACCOUNT_ID,
                graph_message_id=f"benchmark-{case.case_id}",
                internet_message_id=None,
                subject=case.case_id,
                sender_domain=case.input.sender_domain,
                received_at=case.input.received_at,
                outlook_web_link=None,
                body_hash=None,
                has_attachments=False,
            )
        )
        for row in placeholder_secure_link_rows(
            source_email_id=case.source_email_id,
            link_refs=case.input.allowed_link_refs,
        ):
            session.add(row)

    prepared = SafePreparedEmail(
        source_email_id=case.source_email_id,
        sender_domain=case.input.sender_domain,
        received_at=case.input.received_at,
        sanitized_text=case.input.sanitized_text,
        link_refs=case.input.allowed_link_refs,
        prefilter_decision=case.input.prefilter_decision,
    )
    extraction_service = RecruitmentExtractionService(model=replay_model_for((case,)))
    activities = ReplayPreparationActivities(
        prepared=prepared,
        extraction_service=extraction_service,
        entity_resolution_service=RecruitmentEntityResolutionService(
            extraction_service=extraction_service,
            company_resolver=CompanyResolver(SqlAlchemyCompanyRepository(session_factory)),
            audit_repository=SqlAlchemyCompanyResolutionAuditRepository(session_factory),
        ),
    )
    timing = StageTimingPersistence(SqlAlchemyWorkflowPersistence(session_factory))
    context = RecruitmentGraphContext(
        activities=activities,
        domain=RecruitmentDomainService(SqlAlchemyRecruitmentDomainStore(session_factory)),
        persistence=timing,
        calendar=DisabledCalendarSync(),
        clock=_FixedClock(case.input.received_at + timedelta(hours=1)),
    )
    runner = RecruitmentWorkflowRunner(
        graph=build_recruitment_graph(checkpointer=checkpointer),
        context=context,
    )

    started = perf_counter()
    try:
        invocation = await runner.start(
            WorkflowStartRequest(
                source_email_id=case.source_email_id,
                model_deployment="benchmark-replay",
                processing_run_id=case.processing_run_id,
            )
        )
    except Exception as exc:
        return PipelineCaseResult(
            case_id=case.case_id,
            passed=False,
            expected_outcome=expected.outcome.value,
            actual_outcome=f"failed:{type(exc).__name__}",
            mismatches=(sanitized_workflow_failure(exc),),
            duration_ms=(perf_counter() - started) * 1000,
            stage_durations_ms=timing.stage_durations_ms,
        )
    duration_ms = (perf_counter() - started) * 1000

    if invocation.interrupted:
        actual_outcome = PipelineOutcome.NEEDS_REVIEW.value
    else:
        actual_outcome = str(invocation.state["status"])
    mismatches = list(
        await _collect_mismatches(
            case,
            expected,
            actual_outcome=actual_outcome,
            interrupt_payloads=invocation.interrupt_payloads,
            final_application_id=invocation.state.get("application_id"),
            session_factory=session_factory,
        )
    )
    return PipelineCaseResult(
        case_id=case.case_id,
        passed=not mismatches,
        expected_outcome=expected.outcome.value,
        actual_outcome=actual_outcome,
        mismatches=tuple(mismatches),
        duration_ms=duration_ms,
        stage_durations_ms=timing.stage_durations_ms,
    )


async def _collect_mismatches(
    case: BenchmarkCase,
    expected: ExpectedDomainOutcome,
    *,
    actual_outcome: str,
    interrupt_payloads: tuple[dict[str, object], ...],
    final_application_id: object,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if actual_outcome != expected.outcome.value:
        mismatches.append(f"outcome expected={expected.outcome.value} actual={actual_outcome}")
        return tuple(mismatches)

    async with session_factory() as session:
        source = await session.get(SourceEmailModel, case.source_email_id)
        if source is None:
            return (*mismatches, "source email row disappeared")

        if expected.outcome is PipelineOutcome.NEEDS_REVIEW:
            expected_status = "needs_review"
            payload_type = (
                str(interrupt_payloads[0].get("review_type")) if interrupt_payloads else None
            )
            expected_review = expected.review_type.value if expected.review_type else None
            if payload_type != expected_review:
                mismatches.append(f"review_type expected={expected_review} actual={payload_type}")
            review_row = await session.scalar(
                select(ReviewItemModel).where(
                    ReviewItemModel.processing_run_id == case.processing_run_id
                )
            )
            if review_row is None:
                mismatches.append("review row was not persisted")
            elif review_row.review_type != expected_review:
                mismatches.append(
                    "persisted review_type "
                    f"expected={expected_review} actual={review_row.review_type}"
                )
        elif expected.outcome is PipelineOutcome.IGNORED:
            expected_status = "ignored"
        else:
            expected_status = "processed"
            mismatches.extend(
                await _collect_completed_mismatches(
                    expected,
                    final_application_id=final_application_id,
                    session=session,
                )
            )

        if source.processing_status != expected_status:
            mismatches.append(
                "source processing_status "
                f"expected={expected_status} actual={source.processing_status}"
            )
    return tuple(mismatches)


async def _collect_completed_mismatches(
    expected: ExpectedDomainOutcome,
    *,
    final_application_id: object,
    session: AsyncSession,
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if final_application_id is None:
        return ("application_id missing from final state",)
    application_id = UUID(str(final_application_id))
    application = await session.get(ApplicationModel, application_id)
    if application is None:
        return ("application row was not persisted",)

    expected_status = expected.application_status
    if expected_status is not None and application.status != expected_status.value:
        mismatches.append(
            f"application_status expected={expected_status.value} actual={application.status}"
        )

    events = (
        (
            await session.execute(
                select(RecruitmentEventModel).where(
                    RecruitmentEventModel.application_id == application_id
                )
            )
        )
        .scalars()
        .all()
    )
    if expected.event is None:
        if events:
            mismatches.append(f"expected no event rows, found {len(events)}")
    elif len(events) != 1:
        mismatches.append(f"expected exactly one event row, found {len(events)}")
    else:
        event = events[0]
        if event.type != expected.event.type.value:
            mismatches.append(
                f"event_type expected={expected.event.type.value} actual={event.type}"
            )
        if _instant(event.starts_at) != _instant(expected.event.starts_at):
            mismatches.append("event starts_at mismatch")
        if _instant(event.deadline_at) != _instant(expected.event.deadline_at):
            mismatches.append("event deadline_at mismatch")
        if event.timezone != expected.event.timezone:
            mismatches.append(
                f"event timezone expected={expected.event.timezone} actual={event.timezone}"
            )

    action_count = await session.scalar(
        select(func.count())
        .select_from(ActionItemModel)
        .where(ActionItemModel.application_id == application_id)
    )
    if int(action_count or 0) != expected.action_item_count:
        mismatches.append(
            f"action_item_count expected={expected.action_item_count} actual={action_count}"
        )
    return tuple(mismatches)


async def _count_checkpoint_privacy_violations(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Count checkpoint rows containing plaintext URL material (must be zero)."""
    total = 0
    async with session_factory() as session:
        for table in ("checkpoint_blobs", "checkpoint_writes"):
            clauses = " OR ".join(
                f"position(convert_to('{pattern}', 'UTF8') in blob) > 0"
                for pattern in _CHECKPOINT_URL_PATTERNS
            )
            count = await session.scalar(
                text(
                    f"SELECT count(*) FROM agent_checkpoint.{table} "
                    f"WHERE blob IS NOT NULL AND ({clauses})"
                )
            )
            total += int(count or 0)
        json_clauses = " OR ".join(
            f"(checkpoint::text || coalesce(metadata::text, '')) LIKE '%{pattern}%'"
            for pattern in _CHECKPOINT_URL_PATTERNS
        )
        count = await session.scalar(
            text(f"SELECT count(*) FROM agent_checkpoint.checkpoints WHERE {json_clauses}")
        )
        total += int(count or 0)
    return total


def _aggregate(
    results: tuple[PipelineCaseResult, ...],
    checkpoint_privacy_violations: int,
) -> PipelineAggregate:
    durations = [result.duration_ms for result in results]
    stage_samples: dict[str, list[float]] = {}
    for result in results:
        for stage, value in result.stage_durations_ms.items():
            stage_samples.setdefault(stage, []).append(value)
    outcome_counts: dict[str, int] = {}
    for result in results:
        outcome_counts[result.actual_outcome] = outcome_counts.get(result.actual_outcome, 0) + 1
    passed = sum(1 for result in results if result.passed)
    return PipelineAggregate(
        total_cases=len(results),
        passed_cases=passed,
        pass_rate=passed / len(results),
        outcome_counts=dict(sorted(outcome_counts.items())),
        run_duration_p50_ms=percentile(durations, 0.5) if durations else None,
        run_duration_p95_ms=percentile(durations, 0.95) if durations else None,
        stage_duration_p50_ms={
            stage: percentile(samples, 0.5) for stage, samples in sorted(stage_samples.items())
        },
        stage_duration_p95_ms={
            stage: percentile(samples, 0.95) for stage, samples in sorted(stage_samples.items())
        },
        checkpoint_privacy_violations=checkpoint_privacy_violations,
    )


def _instant(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)
