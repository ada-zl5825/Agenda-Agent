"""Baseline comparison and regression gating for benchmark reports."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from benchmarks.harness.report import ExtractionRunReport, PipelineRunReport

#: Higher-is-better metrics gated against the recorded baseline. Values are the
#: maximum tolerated absolute drop (in rate points) before the gate fails.
RELATIVE_DROP_LIMITS: dict[str, float] = {
    "relevant_f1": 0.02,
    "event_type_accuracy": 0.02,
    "validation_status_match_rate": 0.02,
    "exact_case_match_rate": 0.05,
    "field_company_raw_match_rate": 0.05,
    "field_role_raw_match_rate": 0.05,
    "field_event_datetime_match_rate": 0.05,
    "field_deadline_match_rate": 0.05,
    "field_timezone_explicit_match_rate": 0.05,
    "field_action_required_match_rate": 0.05,
    "field_action_link_ref_match_rate": 0.05,
    "pipeline_pass_rate": 0.0,
}

#: Latency regressions warn rather than fail: shared cloud infrastructure makes
#: wall-clock times noisy, and quality gates must stay deterministic.
LATENCY_WARN_RATIO = 1.5
LATENCY_METRICS = ("latency_p95_ms", "run_duration_p95_ms")


class GateThresholds(BaseModel):
    """Absolute safety limits that apply even without a baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_missed_review_count: int = 0
    max_schema_failure_rate: float = 0.02
    min_pipeline_pass_rate: float = 1.0
    max_checkpoint_privacy_violations: int = 0


class BaselineEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    recorded_at: datetime
    git_sha: str | None
    dataset_version: str
    metrics: dict[str, float]


class BaselineFile(BaseModel):
    """Committed benchmark history keyed by suite and execution mode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    suites: dict[str, dict[str, BaselineEntry]] = Field(default_factory=dict)

    def entry(self, suite: str, mode: str) -> BaselineEntry | None:
        return self.suites.get(suite, {}).get(mode)


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...]

    def render(self) -> str:
        lines = ["Gate: PASSED" if self.passed else "Gate: FAILED"]
        lines += [f"FAIL: {failure}" for failure in self.failures]
        lines += [f"WARN: {warning}" for warning in self.warnings]
        return "\n".join(lines)


def load_baseline(path: Path) -> BaselineFile | None:
    if not path.is_file():
        return None
    return BaselineFile.model_validate_json(path.read_text(encoding="utf-8"))


def update_baseline(
    path: Path,
    *,
    report: ExtractionRunReport | PipelineRunReport,
) -> None:
    """Record the report metrics as the new baseline for its suite and mode."""
    baseline = load_baseline(path) or BaselineFile()
    suites = {suite: dict(entries) for suite, entries in baseline.suites.items()}
    suites.setdefault(report.meta.suite, {})[report.meta.mode] = BaselineEntry(
        recorded_at=report.meta.run_at,
        git_sha=report.meta.git_sha,
        dataset_version=report.meta.dataset_version,
        metrics=report.gate_metrics(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        BaselineFile(suites=suites).model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def evaluate_gate(
    report: ExtractionRunReport | PipelineRunReport,
    *,
    baseline: BaselineFile | None,
    thresholds: GateThresholds | None = None,
) -> GateResult:
    limits = thresholds or GateThresholds()
    metrics = report.gate_metrics()
    failures: list[str] = []
    warnings: list[str] = []

    _check_absolute(metrics, limits, failures)
    entry = None if baseline is None else baseline.entry(report.meta.suite, report.meta.mode)
    if entry is None:
        warnings.append(
            f"no baseline recorded for {report.meta.suite}/{report.meta.mode}; "
            "absolute thresholds only"
        )
    elif entry.dataset_version != report.meta.dataset_version:
        warnings.append(
            f"baseline dataset {entry.dataset_version} differs from "
            f"{report.meta.dataset_version}; relative comparison skipped"
        )
    else:
        _check_relative(metrics, entry.metrics, failures, warnings)
    return GateResult(
        passed=not failures,
        failures=tuple(failures),
        warnings=tuple(warnings),
    )


def _check_absolute(
    metrics: dict[str, float],
    limits: GateThresholds,
    failures: list[str],
) -> None:
    missed = metrics.get("missed_review_count")
    if missed is not None and missed > limits.max_missed_review_count:
        failures.append(
            f"missed_review_count {missed:.0f} exceeds "
            f"{limits.max_missed_review_count} (ambiguous cases silently passed)"
        )
    schema_failure = metrics.get("schema_failure_rate")
    if schema_failure is not None and schema_failure > limits.max_schema_failure_rate:
        failures.append(
            f"schema_failure_rate {schema_failure:.3f} exceeds {limits.max_schema_failure_rate:.3f}"
        )
    pass_rate = metrics.get("pipeline_pass_rate")
    if pass_rate is not None and pass_rate < limits.min_pipeline_pass_rate:
        failures.append(
            f"pipeline_pass_rate {pass_rate:.3f} is below {limits.min_pipeline_pass_rate:.3f}"
        )
    violations = metrics.get("checkpoint_privacy_violations")
    if violations is not None and violations > limits.max_checkpoint_privacy_violations:
        failures.append(
            f"checkpoint_privacy_violations {violations:.0f} exceeds "
            f"{limits.max_checkpoint_privacy_violations}"
        )


def _check_relative(
    metrics: dict[str, float],
    baseline_metrics: dict[str, float],
    failures: list[str],
    warnings: list[str],
) -> None:
    for name, max_drop in RELATIVE_DROP_LIMITS.items():
        current = metrics.get(name)
        recorded = baseline_metrics.get(name)
        if current is None or recorded is None:
            continue
        if current < recorded - max_drop:
            failures.append(
                f"{name} dropped from {recorded:.3f} to {current:.3f} (allowed drop {max_drop:.3f})"
            )
    for name in LATENCY_METRICS:
        current = metrics.get(name)
        recorded = baseline_metrics.get(name)
        # Sub-millisecond baselines (replay mode) carry no latency signal.
        if current is None or recorded is None or recorded < 1.0:
            continue
        if current > recorded * LATENCY_WARN_RATIO:
            warnings.append(
                f"{name} rose from {recorded:.0f}ms to {current:.0f}ms "
                f"(>{LATENCY_WARN_RATIO:.1f}x baseline)"
            )
