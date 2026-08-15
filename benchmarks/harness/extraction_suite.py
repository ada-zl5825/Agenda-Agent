"""L1 extraction-quality suite: replay (free) and live (Azure OpenAI) modes.

Both modes run the production ``RecruitmentExtractionService`` so the exact
deployed validator judges every output. Replay feeds the recorded reference
responses (dataset and harness health, zero cost); live invokes the real
structured-output model behind the production port.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal
from uuid import UUID

from benchmarks.harness.models import BenchmarkCase, BenchmarkDataset
from benchmarks.harness.report import ExtractionRunReport, RunMetadata
from benchmarks.harness.scorers import (
    ExtractionCaseResult,
    aggregate_extraction_results,
    score_extraction_case,
)
from recruitment_agent.application.errors import ExtractionInvocationError
from recruitment_agent.application.recruitment_extraction import (
    RecruitmentExtractionService,
)
from recruitment_agent.extraction.models import (
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)
from recruitment_agent.extraction.ports import RecruitmentExtractionModel
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_VERSION
from recruitment_agent.extraction.usage import consume_extraction_usage

ExtractionSuiteMode = Literal["replay", "live"]


class ReplayExtractionModel:
    """Return the recorded reference output for each benchmark case."""

    def __init__(self, responses: Mapping[UUID, RecruitmentExtraction]) -> None:
        self._responses = dict(responses)

    async def extract(
        self,
        request: RecruitmentExtractionRequest,
    ) -> RecruitmentExtraction:
        return self._responses[request.source_email_id]


def replay_model_for(cases: tuple[BenchmarkCase, ...]) -> ReplayExtractionModel:
    return ReplayExtractionModel({case.source_email_id: case.recorded_response for case in cases})


def build_case_request(case: BenchmarkCase) -> RecruitmentExtractionRequest:
    return RecruitmentExtractionRequest(
        source_email_id=case.source_email_id,
        received_at=case.input.received_at,
        sanitized_text=case.input.sanitized_text,
        allowed_link_refs=case.input.allowed_link_refs,
        prompt_version=RECRUITMENT_EXTRACTION_PROMPT_VERSION,
    )


async def run_extraction_suite(
    dataset: BenchmarkDataset,
    *,
    model: RecruitmentExtractionModel,
    mode: ExtractionSuiteMode,
    model_deployment: str | None = None,
    cases: tuple[BenchmarkCase, ...] | None = None,
    concurrency: int = 4,
    git_sha: str | None = None,
    input_token_price_per_1m: float | None = None,
    output_token_price_per_1m: float | None = None,
) -> ExtractionRunReport:
    selected = cases if cases is not None else dataset.cases
    if not selected:
        raise ValueError("no benchmark cases selected")
    service = RecruitmentExtractionService(model=model)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run_case(case: BenchmarkCase) -> ExtractionCaseResult:
        request = build_case_request(case)
        async with semaphore:
            started = perf_counter()
            try:
                outcome = await service.extract_request(request)
            except ExtractionInvocationError:
                consume_extraction_usage()
                return score_extraction_case(
                    case,
                    extraction=None,
                    validation=None,
                    error="invocation_error",
                    latency_ms=(perf_counter() - started) * 1000,
                )
            except Exception as exc:
                consume_extraction_usage()
                return score_extraction_case(
                    case,
                    extraction=None,
                    validation=None,
                    error=f"unexpected:{type(exc).__name__}",
                    latency_ms=(perf_counter() - started) * 1000,
                )
            wall_ms = (perf_counter() - started) * 1000
        usage = consume_extraction_usage()
        return score_extraction_case(
            case,
            extraction=outcome.extraction,
            validation=outcome.validation,
            latency_ms=float(usage.latency_ms) if usage is not None else wall_ms,
            prompt_tokens=None if usage is None else usage.prompt_tokens,
            completion_tokens=None if usage is None else usage.completion_tokens,
        )

    results = tuple(await asyncio.gather(*(run_case(case) for case in selected)))
    aggregate = aggregate_extraction_results(
        results,
        input_token_price_per_1m=input_token_price_per_1m,
        output_token_price_per_1m=output_token_price_per_1m,
    )
    meta = RunMetadata(
        suite="extraction",
        mode=mode,
        run_at=datetime.now(UTC),
        git_sha=git_sha,
        prompt_version=RECRUITMENT_EXTRACTION_PROMPT_VERSION,
        model_deployment=model_deployment,
        dataset_name=dataset.manifest.dataset,
        dataset_version=dataset.manifest.version,
        dataset_case_count=dataset.manifest.case_count,
        executed_case_count=len(selected),
    )
    return ExtractionRunReport(meta=meta, aggregate=aggregate, cases=results)
