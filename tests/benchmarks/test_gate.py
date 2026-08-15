"""Gate semantics: absolute safety limits and baseline regression checks."""

from datetime import UTC, datetime

from benchmarks.harness.gate import BaselineEntry, BaselineFile, evaluate_gate
from benchmarks.harness.report import (
    ExtractionRunReport,
    PipelineAggregate,
    PipelineRunReport,
    RunMetadata,
)
from benchmarks.harness.scorers import ExtractionAggregate


def _meta(suite: str, mode: str) -> RunMetadata:
    return RunMetadata(
        suite=suite,
        mode=mode,
        run_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
        git_sha=None,
        prompt_version="recruitment-extraction-v2",
        model_deployment=None,
        dataset_name="extraction",
        dataset_version="v1",
        dataset_case_count=60,
        executed_case_count=60,
    )


def _extraction_aggregate(**overrides: object) -> ExtractionAggregate:
    values: dict[str, object] = {
        "total_cases": 60,
        "succeeded_cases": 60,
        "failed_cases": 0,
        "schema_failure_rate": 0.0,
        "relevant_true_positives": 49,
        "relevant_false_positives": 0,
        "relevant_false_negatives": 0,
        "relevant_true_negatives": 11,
        "relevant_precision": 1.0,
        "relevant_recall": 1.0,
        "relevant_f1": 1.0,
        "event_type_accuracy": 1.0,
        "event_type_confusion": {},
        "field_match_rates": {},
        "exact_case_match_rate": 1.0,
        "validation_status_match_rate": 1.0,
        "validation_issues_match_rate": 1.0,
        "missed_review_count": 0,
        "false_review_count": 0,
        "latency_p50_ms": None,
        "latency_p95_ms": None,
        "total_prompt_tokens": None,
        "total_completion_tokens": None,
        "mean_prompt_tokens": None,
        "mean_completion_tokens": None,
        "estimated_cost_usd": None,
    }
    values.update(overrides)
    return ExtractionAggregate.model_validate(values)


def _extraction_report(**overrides: object) -> ExtractionRunReport:
    return ExtractionRunReport(
        meta=_meta("extraction", "live"),
        aggregate=_extraction_aggregate(**overrides),
        cases=(),
    )


def _baseline(metrics: dict[str, float], *, dataset_version: str = "v1") -> BaselineFile:
    return BaselineFile(
        suites={
            "extraction": {
                "live": BaselineEntry(
                    recorded_at=datetime(2026, 8, 1, tzinfo=UTC),
                    git_sha=None,
                    dataset_version=dataset_version,
                    metrics=metrics,
                )
            }
        }
    )


def test_missed_review_fails_even_without_baseline() -> None:
    result = evaluate_gate(_extraction_report(missed_review_count=1), baseline=None)
    assert not result.passed
    assert any("missed_review_count" in failure for failure in result.failures)


def test_schema_failure_rate_above_limit_fails() -> None:
    result = evaluate_gate(
        _extraction_report(schema_failure_rate=0.05, failed_cases=3, succeeded_cases=57),
        baseline=None,
    )
    assert not result.passed


def test_missing_baseline_warns_but_passes() -> None:
    result = evaluate_gate(_extraction_report(), baseline=None)
    assert result.passed
    assert any("no baseline" in warning for warning in result.warnings)


def test_relative_drop_beyond_tolerance_fails() -> None:
    baseline = _baseline({"relevant_f1": 1.0})
    result = evaluate_gate(_extraction_report(relevant_f1=0.9), baseline=baseline)
    assert not result.passed
    assert any("relevant_f1" in failure for failure in result.failures)


def test_relative_drop_within_tolerance_passes() -> None:
    baseline = _baseline({"relevant_f1": 1.0})
    result = evaluate_gate(_extraction_report(relevant_f1=0.99), baseline=baseline)
    assert result.passed


def test_dataset_version_mismatch_skips_relative_comparison() -> None:
    baseline = _baseline({"relevant_f1": 1.0}, dataset_version="v0")
    result = evaluate_gate(_extraction_report(relevant_f1=0.5), baseline=baseline)
    assert result.passed
    assert any("relative comparison skipped" in warning for warning in result.warnings)


def test_latency_regression_warns_instead_of_failing() -> None:
    baseline = _baseline({"latency_p95_ms": 100.0})
    result = evaluate_gate(
        _extraction_report(latency_p50_ms=150.0, latency_p95_ms=200.0),
        baseline=baseline,
    )
    assert result.passed
    assert any("latency_p95_ms" in warning for warning in result.warnings)


def test_pipeline_pass_rate_below_one_fails() -> None:
    report = PipelineRunReport(
        meta=_meta("pipeline", "replay"),
        aggregate=PipelineAggregate(
            total_cases=21,
            passed_cases=20,
            pass_rate=20 / 21,
            outcome_counts={"completed": 12},
            run_duration_p50_ms=10.0,
            run_duration_p95_ms=20.0,
            stage_duration_p50_ms={},
            stage_duration_p95_ms={},
            checkpoint_privacy_violations=0,
        ),
        cases=(),
    )
    result = evaluate_gate(report, baseline=None)
    assert not result.passed
    assert any("pipeline_pass_rate" in failure for failure in result.failures)


def test_checkpoint_privacy_violation_fails() -> None:
    report = PipelineRunReport(
        meta=_meta("pipeline", "replay"),
        aggregate=PipelineAggregate(
            total_cases=21,
            passed_cases=21,
            pass_rate=1.0,
            outcome_counts={},
            run_duration_p50_ms=None,
            run_duration_p95_ms=None,
            stage_duration_p50_ms={},
            stage_duration_p95_ms={},
            checkpoint_privacy_violations=1,
        ),
        cases=(),
    )
    result = evaluate_gate(report, baseline=None)
    assert not result.passed
    assert any("privacy" in failure for failure in result.failures)
