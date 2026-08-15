"""Deterministic field-level scoring for extraction benchmark runs."""

import math
from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from benchmarks.harness.models import BenchmarkCase
from recruitment_agent.extraction.models import (
    ExtractionValidationResult,
    ExtractionValidationStatus,
    RecruitmentExtraction,
)

SCORED_FIELDS: tuple[str, ...] = (
    "relevant",
    "event_type",
    "company_raw",
    "role_raw",
    "action_required",
    "action_link_ref",
    "event_datetime",
    "deadline",
    "timezone_explicit",
)


class ExtractionCaseResult(BaseModel):
    """Privacy-safe scored outcome of one benchmark case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    tags: tuple[str, ...]
    succeeded: bool
    error: str | None = None
    field_matches: dict[str, bool] = Field(default_factory=dict)
    expected_relevant: bool
    actual_relevant: bool | None = None
    expected_event_type: str
    actual_event_type: str | None = None
    expected_validation_status: str
    actual_validation_status: str | None = None
    validation_status_match: bool = False
    validation_issues_match: bool = False
    missed_review: bool = False
    false_review: bool = False
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def all_fields_match(self) -> bool:
        return self.succeeded and all(self.field_matches.values())


class ExtractionAggregate(BaseModel):
    """Suite-level quality, safety, and performance metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_cases: int
    succeeded_cases: int
    failed_cases: int
    schema_failure_rate: float
    relevant_true_positives: int
    relevant_false_positives: int
    relevant_false_negatives: int
    relevant_true_negatives: int
    relevant_precision: float | None
    relevant_recall: float | None
    relevant_f1: float | None
    event_type_accuracy: float | None
    event_type_confusion: dict[str, int]
    field_match_rates: dict[str, float]
    exact_case_match_rate: float | None
    validation_status_match_rate: float | None
    validation_issues_match_rate: float | None
    missed_review_count: int
    false_review_count: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    total_prompt_tokens: int | None
    total_completion_tokens: int | None
    mean_prompt_tokens: float | None
    mean_completion_tokens: float | None
    estimated_cost_usd: float | None

    def gate_metrics(self) -> dict[str, float]:
        """Flatten the metrics consumed by baseline comparison and gating."""
        metrics: dict[str, float] = {
            "schema_failure_rate": self.schema_failure_rate,
            "missed_review_count": float(self.missed_review_count),
            "false_review_count": float(self.false_review_count),
        }
        optional: dict[str, float | None] = {
            "relevant_f1": self.relevant_f1,
            "event_type_accuracy": self.event_type_accuracy,
            "exact_case_match_rate": self.exact_case_match_rate,
            "validation_status_match_rate": self.validation_status_match_rate,
            "validation_issues_match_rate": self.validation_issues_match_rate,
            "latency_p95_ms": self.latency_p95_ms,
        }
        for field_name, rate in self.field_match_rates.items():
            optional[f"field_{field_name}_match_rate"] = rate
        metrics.update({name: value for name, value in optional.items() if value is not None})
        return metrics


def normalize_free_text(value: str | None) -> str | None:
    """Compare evidence text without penalizing case or whitespace variance."""
    if value is None:
        return None
    normalized = " ".join(value.casefold().split())
    return normalized or None


def datetimes_match(
    expected: datetime | None,
    actual: datetime | None,
    *,
    timezone_explicit_expected: bool,
) -> bool:
    """Compare instants; placeholder datetimes must also keep the +00:00 offset.

    When the source names no timezone the prompt contract requires a
    non-authoritative ``+00:00`` offset carrying the wall-clock reading, so an
    instant-equal value with a different offset would still be wrong.
    """
    if expected is None or actual is None:
        return expected is None and actual is None
    if expected != actual:
        return False
    if not timezone_explicit_expected:
        return actual.utcoffset() == timedelta(0)
    return True


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile over a non-empty sample."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must be within (0, 1]")
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def score_extraction_case(
    case: BenchmarkCase,
    *,
    extraction: RecruitmentExtraction | None,
    validation: ExtractionValidationResult | None,
    error: str | None = None,
    latency_ms: float | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> ExtractionCaseResult:
    expected = case.expected
    if extraction is None or validation is None:
        return ExtractionCaseResult(
            case_id=case.case_id,
            tags=case.tags,
            succeeded=False,
            error=error or "extraction_failed",
            expected_relevant=expected.relevant,
            expected_event_type=expected.event_type.value,
            expected_validation_status=expected.validation_status.value,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    field_matches = {
        "relevant": extraction.relevant == expected.relevant,
        "event_type": extraction.event_type is expected.event_type,
        "company_raw": (
            normalize_free_text(extraction.company_raw) == normalize_free_text(expected.company_raw)
        ),
        "role_raw": (
            normalize_free_text(extraction.role_raw) == normalize_free_text(expected.role_raw)
        ),
        "action_required": extraction.action_required == expected.action_required,
        "action_link_ref": extraction.action_link_ref == expected.action_link_ref,
        "event_datetime": datetimes_match(
            expected.event_datetime,
            extraction.event_datetime,
            timezone_explicit_expected=expected.timezone_explicit,
        ),
        "deadline": datetimes_match(
            expected.deadline,
            extraction.deadline,
            timezone_explicit_expected=expected.timezone_explicit,
        ),
        "timezone_explicit": extraction.timezone_explicit == expected.timezone_explicit,
    }
    actual_status = validation.status
    expected_status = expected.validation_status
    actual_issues = tuple(sorted(issue.code.value for issue in validation.issues))
    expected_issues = tuple(sorted(expected.validation_issues))
    return ExtractionCaseResult(
        case_id=case.case_id,
        tags=case.tags,
        succeeded=True,
        field_matches=field_matches,
        expected_relevant=expected.relevant,
        actual_relevant=extraction.relevant,
        expected_event_type=expected.event_type.value,
        actual_event_type=extraction.event_type.value,
        expected_validation_status=expected_status.value,
        actual_validation_status=actual_status.value,
        validation_status_match=actual_status is expected_status,
        validation_issues_match=actual_issues == expected_issues,
        missed_review=(
            expected_status is ExtractionValidationStatus.NEEDS_REVIEW
            and actual_status is ExtractionValidationStatus.VALID
        ),
        false_review=(
            expected_status is ExtractionValidationStatus.VALID
            and actual_status is ExtractionValidationStatus.NEEDS_REVIEW
        ),
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def aggregate_extraction_results(
    results: Sequence[ExtractionCaseResult],
    *,
    input_token_price_per_1m: float | None = None,
    output_token_price_per_1m: float | None = None,
) -> ExtractionAggregate:
    if not results:
        raise ValueError("cannot aggregate an empty benchmark run")
    total = len(results)
    scored = [result for result in results if result.succeeded]
    failed = total - len(scored)

    true_positives = sum(1 for r in scored if r.expected_relevant and r.actual_relevant is True)
    false_positives = sum(
        1 for r in scored if not r.expected_relevant and r.actual_relevant is True
    )
    false_negatives = sum(
        1 for r in scored if r.expected_relevant and r.actual_relevant is False
    ) + sum(1 for r in results if not r.succeeded and r.expected_relevant)
    true_negatives = sum(
        1 for r in scored if not r.expected_relevant and r.actual_relevant is False
    )
    precision = _rate(true_positives, true_positives + false_positives)
    recall = _rate(true_positives, true_positives + false_negatives)
    f1: float | None = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)

    relevant_expected = [r for r in scored if r.expected_relevant]
    event_type_accuracy = _rate(
        sum(1 for r in relevant_expected if r.field_matches.get("event_type", False)),
        len(relevant_expected),
    )
    confusion: dict[str, int] = {}
    for result in relevant_expected:
        key = f"{result.expected_event_type}->{result.actual_event_type}"
        confusion[key] = confusion.get(key, 0) + 1

    field_match_rates = {
        field_name: rate
        for field_name in SCORED_FIELDS
        if (
            rate := _rate(
                sum(1 for r in scored if r.field_matches.get(field_name, False)),
                len(scored),
            )
        )
        is not None
    }
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    prompt_tokens = [r.prompt_tokens for r in results if r.prompt_tokens is not None]
    completion_tokens = [r.completion_tokens for r in results if r.completion_tokens is not None]
    total_prompt = sum(prompt_tokens) if prompt_tokens else None
    total_completion = sum(completion_tokens) if completion_tokens else None
    estimated_cost: float | None = None
    if (
        total_prompt is not None
        and total_completion is not None
        and input_token_price_per_1m is not None
        and output_token_price_per_1m is not None
    ):
        estimated_cost = (
            total_prompt * input_token_price_per_1m + total_completion * output_token_price_per_1m
        ) / 1_000_000

    return ExtractionAggregate(
        total_cases=total,
        succeeded_cases=len(scored),
        failed_cases=failed,
        schema_failure_rate=failed / total,
        relevant_true_positives=true_positives,
        relevant_false_positives=false_positives,
        relevant_false_negatives=false_negatives,
        relevant_true_negatives=true_negatives,
        relevant_precision=precision,
        relevant_recall=recall,
        relevant_f1=f1,
        event_type_accuracy=event_type_accuracy,
        event_type_confusion=dict(sorted(confusion.items())),
        field_match_rates=field_match_rates,
        exact_case_match_rate=_rate(sum(1 for r in scored if r.all_fields_match), len(scored)),
        validation_status_match_rate=_rate(
            sum(1 for r in scored if r.validation_status_match), len(scored)
        ),
        validation_issues_match_rate=_rate(
            sum(1 for r in scored if r.validation_issues_match), len(scored)
        ),
        missed_review_count=sum(1 for r in scored if r.missed_review),
        false_review_count=sum(1 for r in scored if r.false_review),
        latency_p50_ms=percentile(latencies, 0.5) if latencies else None,
        latency_p95_ms=percentile(latencies, 0.95) if latencies else None,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        mean_prompt_tokens=(
            total_prompt / len(prompt_tokens) if total_prompt is not None else None
        ),
        mean_completion_tokens=(
            total_completion / len(completion_tokens) if total_completion is not None else None
        ),
        estimated_cost_usd=estimated_cost,
    )


def _rate(hits: int, total: int) -> float | None:
    return None if total == 0 else hits / total
