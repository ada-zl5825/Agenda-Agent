"""Adapter-boundary usage capture for extraction telemetry."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from recruitment_agent.application.errors import ExtractionInvocationError
from recruitment_agent.extraction.langchain_azure import (
    LangChainRecruitmentExtractionModel,
    sum_usage_tokens,
)
from recruitment_agent.extraction.models import (
    ExtractionUsage,
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)
from recruitment_agent.extraction.usage import (
    consume_extraction_usage,
    record_extraction_usage,
)

_FIXTURE = json.loads(Path("tests/fixtures/extraction/offer.json").read_text(encoding="utf-8"))


class _StaticRunnable:
    def __init__(self, result: RecruitmentExtraction) -> None:
        self._result = result

    async def ainvoke(self, values: dict[str, object]) -> RecruitmentExtraction:
        del values
        return self._result


class _FailingRunnable:
    async def ainvoke(self, values: dict[str, object]) -> RecruitmentExtraction:
        del values
        raise RuntimeError("provider unavailable")


def _request() -> RecruitmentExtractionRequest:
    return RecruitmentExtractionRequest(
        source_email_id=uuid4(),
        received_at=datetime(2026, 8, 13, 9, tzinfo=UTC),
        sanitized_text=str(_FIXTURE["sanitized_text"]),
        allowed_link_refs=(),
        prompt_version="recruitment-extraction-v2",
    )


@pytest.mark.asyncio
async def test_successful_extraction_records_consumable_usage() -> None:
    extraction = RecruitmentExtraction.model_validate(_FIXTURE["response"])
    model = LangChainRecruitmentExtractionModel(runnable=_StaticRunnable(extraction))

    result = await model.extract(_request())

    assert result == extraction
    usage = consume_extraction_usage()
    assert usage is not None
    assert usage.latency_ms >= 0
    # A fake runnable produces no LangChain usage metadata.
    assert usage.prompt_tokens is None
    assert usage.completion_tokens is None
    assert consume_extraction_usage() is None


def test_sum_usage_tokens_ignores_missing_and_non_integer_fields() -> None:
    assert sum_usage_tokens(None, "input_tokens") is None
    assert sum_usage_tokens({}, "input_tokens") is None
    assert sum_usage_tokens({"model": "not-a-dict"}, "input_tokens") is None
    assert (
        sum_usage_tokens(
            {"gpt": {"input_tokens": "12", "output_tokens": 3}},
            "input_tokens",
        )
        is None
    )
    assert (
        sum_usage_tokens(
            {
                "first": {"input_tokens": 10, "output_tokens": 2},
                "second": {"input_tokens": 5},
                "broken": {"input_tokens": None},
            },
            "input_tokens",
        )
        == 15
    )


@pytest.mark.asyncio
async def test_failed_extraction_clears_stale_usage() -> None:
    record_extraction_usage(ExtractionUsage(latency_ms=5))
    model = LangChainRecruitmentExtractionModel(runnable=_FailingRunnable())

    with pytest.raises(ExtractionInvocationError):
        await model.extract(_request())

    assert consume_extraction_usage() is None
