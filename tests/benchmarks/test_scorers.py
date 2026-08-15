"""Scorer semantics: datetime rules, review safety, and aggregation."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from benchmarks.harness.loader import load_dataset
from benchmarks.harness.models import BenchmarkCase
from benchmarks.harness.scorers import (
    aggregate_extraction_results,
    datetimes_match,
    percentile,
    score_extraction_case,
)
from recruitment_agent.extraction.models import (
    ExtractionValidationResult,
    ExtractionValidationStatus,
)

DATASET = load_dataset("extraction", "v1")
CASES_BY_ID = {case.case_id: case for case in DATASET.cases}


def _case(case_id: str) -> BenchmarkCase:
    return CASES_BY_ID[case_id]


def test_explicit_timezone_datetimes_compare_by_instant() -> None:
    expected = datetime(2026, 8, 20, 14, 0, tzinfo=timezone(timedelta(hours=1)))
    actual = datetime(2026, 8, 20, 13, 0, tzinfo=UTC)
    assert datetimes_match(expected, actual, timezone_explicit_expected=True)


def test_placeholder_datetimes_must_keep_zero_offset() -> None:
    expected = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
    same_instant_wrong_offset = datetime(2026, 8, 20, 15, 0, tzinfo=timezone(timedelta(hours=1)))
    assert not datetimes_match(
        expected,
        same_instant_wrong_offset,
        timezone_explicit_expected=False,
    )
    assert datetimes_match(expected, expected, timezone_explicit_expected=False)


def test_null_datetime_expectations() -> None:
    moment = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
    assert datetimes_match(None, None, timezone_explicit_expected=False)
    assert not datetimes_match(None, moment, timezone_explicit_expected=False)
    assert not datetimes_match(moment, None, timezone_explicit_expected=True)


def test_missed_review_is_flagged_when_ambiguity_passes_validation() -> None:
    case = _case("interview_en_missing_tz")
    result = score_extraction_case(
        case,
        extraction=case.recorded_response,
        validation=ExtractionValidationResult(
            status=ExtractionValidationStatus.VALID,
            issues=(),
        ),
    )
    assert result.missed_review
    assert not result.validation_status_match


def test_false_review_is_flagged_when_clear_case_needs_review() -> None:
    case = _case("offer_en_simple")
    result = score_extraction_case(
        case,
        extraction=case.recorded_response,
        validation=ExtractionValidationResult(
            status=ExtractionValidationStatus.NEEDS_REVIEW,
            issues=(),
        ),
    )
    assert result.false_review
    assert not result.missed_review


def test_failed_case_counts_into_schema_failure_rate() -> None:
    case = _case("offer_en_simple")
    failed = score_extraction_case(
        case,
        extraction=None,
        validation=None,
        error="invocation_error",
    )
    assert not failed.succeeded
    scored = score_extraction_case(
        case,
        extraction=case.recorded_response,
        validation=ExtractionValidationResult(
            status=ExtractionValidationStatus.VALID,
            issues=(),
        ),
    )
    aggregate = aggregate_extraction_results((failed, scored))
    assert aggregate.total_cases == 2
    assert aggregate.failed_cases == 1
    assert aggregate.schema_failure_rate == pytest.approx(0.5)
    # A failed relevant case is a recall miss, never a silent pass.
    assert aggregate.relevant_false_negatives == 1
    assert aggregate.missed_review_count == 0


def test_percentile_uses_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 0.5) == 20.0
    assert percentile(values, 0.95) == 40.0
    with pytest.raises(ValueError, match="at least one value"):
        percentile([], 0.5)
