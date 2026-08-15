"""Versioned benchmark run reports with JSON and Markdown renderings."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from benchmarks.harness.scorers import ExtractionAggregate, ExtractionCaseResult

HARNESS_VERSION = "1"


class RunMetadata(BaseModel):
    """Everything needed to reproduce and compare one benchmark run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    suite: str
    mode: str
    run_at: datetime
    git_sha: str | None
    prompt_version: str
    model_deployment: str | None
    dataset_name: str
    dataset_version: str
    dataset_case_count: int
    executed_case_count: int
    harness_version: str = HARNESS_VERSION


class ExtractionRunReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    meta: RunMetadata
    aggregate: ExtractionAggregate
    cases: tuple[ExtractionCaseResult, ...]

    def gate_metrics(self) -> dict[str, float]:
        return self.aggregate.gate_metrics()


class PipelineCaseResult(BaseModel):
    """Assertion outcome for one full-workflow benchmark case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    passed: bool
    expected_outcome: str
    actual_outcome: str
    mismatches: tuple[str, ...] = ()
    duration_ms: float
    stage_durations_ms: dict[str, float] = Field(default_factory=dict)


class PipelineAggregate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_cases: int
    passed_cases: int
    pass_rate: float
    outcome_counts: dict[str, int]
    run_duration_p50_ms: float | None
    run_duration_p95_ms: float | None
    stage_duration_p50_ms: dict[str, float]
    stage_duration_p95_ms: dict[str, float]
    checkpoint_privacy_violations: int

    def gate_metrics(self) -> dict[str, float]:
        metrics = {
            "pipeline_pass_rate": self.pass_rate,
            "checkpoint_privacy_violations": float(self.checkpoint_privacy_violations),
        }
        if self.run_duration_p95_ms is not None:
            metrics["run_duration_p95_ms"] = self.run_duration_p95_ms
        return metrics


class PipelineRunReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    meta: RunMetadata
    aggregate: PipelineAggregate
    cases: tuple[PipelineCaseResult, ...]

    def gate_metrics(self) -> dict[str, float]:
        return self.aggregate.gate_metrics()


def write_report(
    report: ExtractionRunReport | PipelineRunReport,
    path: Path,
) -> Path:
    """Persist the JSON report and a Markdown summary next to it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    markdown_path = path.with_suffix(".md")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return markdown_path


def render_markdown(report: ExtractionRunReport | PipelineRunReport) -> str:
    if isinstance(report, ExtractionRunReport):
        return _render_extraction_markdown(report)
    return _render_pipeline_markdown(report)


def _meta_lines(meta: RunMetadata) -> list[str]:
    return [
        f"# Benchmark: {meta.suite} ({meta.mode})",
        "",
        f"- Run at: {meta.run_at.isoformat()}",
        f"- Git SHA: {meta.git_sha or 'unknown'}",
        f"- Prompt version: {meta.prompt_version}",
        f"- Model deployment: {meta.model_deployment or 'n/a'}",
        (
            f"- Dataset: {meta.dataset_name} {meta.dataset_version} "
            f"({meta.executed_case_count}/{meta.dataset_case_count} cases)"
        ),
        "",
    ]


def _format_optional(value: float | None, *, as_percent: bool = False) -> str:
    if value is None:
        return "n/a"
    if as_percent:
        return f"{value * 100:.1f}%"
    return f"{value:.1f}"


def _render_extraction_markdown(report: ExtractionRunReport) -> str:
    aggregate = report.aggregate
    lines = _meta_lines(report.meta)
    lines += [
        "## Quality",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases scored | {aggregate.succeeded_cases}/{aggregate.total_cases} |",
        f"| Schema failure rate | {aggregate.schema_failure_rate * 100:.1f}% |",
        f"| Relevant F1 | {_format_optional(aggregate.relevant_f1, as_percent=True)} |",
        (
            "| Relevant P/R | "
            f"{_format_optional(aggregate.relevant_precision, as_percent=True)} / "
            f"{_format_optional(aggregate.relevant_recall, as_percent=True)} |"
        ),
        (
            "| Event type accuracy | "
            f"{_format_optional(aggregate.event_type_accuracy, as_percent=True)} |"
        ),
        (
            "| Exact case match | "
            f"{_format_optional(aggregate.exact_case_match_rate, as_percent=True)} |"
        ),
        (
            "| Validation status match | "
            f"{_format_optional(aggregate.validation_status_match_rate, as_percent=True)} |"
        ),
        f"| Missed reviews (safety) | {aggregate.missed_review_count} |",
        f"| False reviews (noise) | {aggregate.false_review_count} |",
        "",
        "## Field match rates",
        "",
        "| Field | Match rate |",
        "| --- | --- |",
    ]
    lines += [
        f"| {field_name} | {rate * 100:.1f}% |"
        for field_name, rate in aggregate.field_match_rates.items()
    ]
    lines += [
        "",
        "## Performance and cost",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Latency p50 | {_format_optional(aggregate.latency_p50_ms)} ms |",
        f"| Latency p95 | {_format_optional(aggregate.latency_p95_ms)} ms |",
        f"| Prompt tokens | {aggregate.total_prompt_tokens or 'n/a'} |",
        f"| Completion tokens | {aggregate.total_completion_tokens or 'n/a'} |",
        (
            "| Estimated cost (USD) | "
            + (
                f"{aggregate.estimated_cost_usd:.4f}"
                if aggregate.estimated_cost_usd is not None
                else "n/a"
            )
            + " |"
        ),
    ]
    mismatched = [
        case
        for case in report.cases
        if not case.succeeded or not case.all_fields_match or not case.validation_status_match
    ]
    if aggregate.event_type_confusion and any(
        key.split("->")[0] != key.split("->")[1] for key in aggregate.event_type_confusion
    ):
        lines += ["", "## Event type confusion", ""]
        lines += [
            f"- `{pair}`: {count}"
            for pair, count in aggregate.event_type_confusion.items()
            if pair.split("->")[0] != pair.split("->")[1]
        ]
    if mismatched:
        lines += ["", "## Cases needing attention", ""]
        for case in mismatched:
            if not case.succeeded:
                detail = f"failed ({case.error})"
            else:
                missed_fields = ",".join(name for name, ok in case.field_matches.items() if not ok)
                detail = (
                    f"fields[{missed_fields or 'ok'}] "
                    f"validation {case.expected_validation_status}"
                    f"->{case.actual_validation_status}"
                )
            lines.append(f"- `{case.case_id}`: {detail}")
    else:
        lines += ["", "All cases matched the golden labels."]
    return "\n".join(lines) + "\n"


def _render_pipeline_markdown(report: PipelineRunReport) -> str:
    aggregate = report.aggregate
    lines = _meta_lines(report.meta)
    lines += [
        "## Workflow correctness",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases passed | {aggregate.passed_cases}/{aggregate.total_cases} |",
        f"| Pass rate | {aggregate.pass_rate * 100:.1f}% |",
        f"| Checkpoint privacy violations | {aggregate.checkpoint_privacy_violations} |",
        f"| Run duration p50 | {_format_optional(aggregate.run_duration_p50_ms)} ms |",
        f"| Run duration p95 | {_format_optional(aggregate.run_duration_p95_ms)} ms |",
        "",
        "## Outcomes",
        "",
    ]
    lines += [
        f"- {outcome}: {count}" for outcome, count in sorted(aggregate.outcome_counts.items())
    ]
    if aggregate.stage_duration_p95_ms:
        lines += [
            "",
            "## Stage durations (relative regression indicator)",
            "",
            "| Stage | p50 ms | p95 ms |",
            "| --- | --- | --- |",
        ]
        lines += [
            (f"| {stage} | {aggregate.stage_duration_p50_ms.get(stage, 0.0):.1f} | {p95:.1f} |")
            for stage, p95 in aggregate.stage_duration_p95_ms.items()
        ]
    failing = [case for case in report.cases if not case.passed]
    if failing:
        lines += ["", "## Failing cases", ""]
        for case in failing:
            reasons = "; ".join(case.mismatches) or "outcome mismatch"
            lines.append(
                f"- `{case.case_id}`: expected {case.expected_outcome}, "
                f"got {case.actual_outcome} ({reasons})"
            )
    else:
        lines += ["", "All pipeline cases reached the expected domain state."]
    return "\n".join(lines) + "\n"
