"""Command-line entry point for benchmark suites, gates, and baselines.

Run from the repository root, for example:

    uv run python -m benchmarks.cli run extraction --mode replay
    uv run python -m benchmarks.cli run extraction --mode live
    uv run python -m benchmarks.cli run pipeline
    uv run python -m benchmarks.cli gate --report benchmarks/results/<file>.json
"""

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from benchmarks.harness.extraction_suite import (
    ExtractionSuiteMode,
    replay_model_for,
    run_extraction_suite,
)
from benchmarks.harness.gate import (
    GateResult,
    evaluate_gate,
    load_baseline,
    update_baseline,
)
from benchmarks.harness.loader import REPOSITORY_ROOT, load_dataset
from benchmarks.harness.pipeline_suite import run_pipeline_suite
from benchmarks.harness.report import (
    ExtractionRunReport,
    PipelineRunReport,
    render_markdown,
    write_report,
)

RESULTS_DIRECTORY = REPOSITORY_ROOT / "benchmarks" / "results"
DEFAULT_BASELINE = REPOSITORY_ROOT / "benchmarks" / "baselines" / "extraction_v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.handler(args)
    except KeyboardInterrupt:
        print("benchmark interrupted", file=sys.stderr)
        return 2
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmarks",
        description="Engineering benchmarks for the recruitment inbox agent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Execute a benchmark suite.")
    run_subparsers = run_parser.add_subparsers(dest="suite", required=True)

    extraction = run_subparsers.add_parser(
        "extraction",
        help="L1 extraction quality (replay is free; live calls Azure OpenAI).",
    )
    extraction.add_argument("--mode", choices=("replay", "live"), default="replay")
    extraction.add_argument("--dataset-version", default="v1")
    extraction.add_argument(
        "--tags",
        default=None,
        help="Comma-separated tag filter; a case runs when any tag matches.",
    )
    extraction.add_argument("--limit", type=int, default=None)
    extraction.add_argument("--concurrency", type=int, default=4)
    extraction.add_argument("--output", type=Path, default=None)
    extraction.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    extraction.add_argument(
        "--gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Compare against the baseline and fail on regression.",
    )
    extraction.add_argument("--update-baseline", action="store_true")
    extraction.add_argument("--input-token-price-per-1m", type=float, default=None)
    extraction.add_argument("--output-token-price-per-1m", type=float, default=None)
    extraction.set_defaults(handler=_run_extraction)

    pipeline = run_subparsers.add_parser(
        "pipeline",
        help="L2 full-workflow correctness (Docker required for PostgreSQL).",
    )
    pipeline.add_argument("--dataset-version", default="v1")
    pipeline.add_argument(
        "--database-url",
        default=None,
        help="Reuse an existing empty PostgreSQL instead of a testcontainer.",
    )
    pipeline.add_argument("--output", type=Path, default=None)
    pipeline.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    pipeline.add_argument(
        "--gate",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    pipeline.add_argument("--update-baseline", action="store_true")
    pipeline.set_defaults(handler=_run_pipeline)

    gate = subparsers.add_parser("gate", help="Re-evaluate the gate for a stored report.")
    gate.add_argument("--report", type=Path, required=True)
    gate.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    gate.set_defaults(handler=_run_gate)

    baseline = subparsers.add_parser(
        "update-baseline",
        help="Record a stored report as the committed baseline.",
    )
    baseline.add_argument("--report", type=Path, required=True)
    baseline.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    baseline.set_defaults(handler=_run_update_baseline)
    return parser


def _run_extraction(args: argparse.Namespace) -> int:
    dataset = load_dataset("extraction", args.dataset_version)
    tags = (
        frozenset(tag.strip() for tag in args.tags.split(",") if tag.strip()) if args.tags else None
    )
    cases = dataset.filtered(tags=tags, limit=args.limit)
    if not cases:
        print("no cases matched the selection", file=sys.stderr)
        return 2
    mode: ExtractionSuiteMode = args.mode

    async def execute() -> ExtractionRunReport:
        if mode == "replay":
            return await run_extraction_suite(
                dataset,
                model=replay_model_for(cases),
                mode=mode,
                model_deployment=None,
                cases=cases,
                concurrency=args.concurrency,
                git_sha=_git_sha(),
                input_token_price_per_1m=args.input_token_price_per_1m,
                output_token_price_per_1m=args.output_token_price_per_1m,
            )
        from recruitment_agent.config.settings import get_azure_openai_settings
        from recruitment_agent.extraction.langchain_azure import (
            create_azure_recruitment_extraction_model,
        )

        settings = get_azure_openai_settings()
        model = create_azure_recruitment_extraction_model(settings)
        try:
            return await run_extraction_suite(
                dataset,
                model=model,
                mode=mode,
                model_deployment=settings.azure_openai_deployment,
                cases=cases,
                concurrency=args.concurrency,
                git_sha=_git_sha(),
                input_token_price_per_1m=args.input_token_price_per_1m,
                output_token_price_per_1m=args.output_token_price_per_1m,
            )
        finally:
            await model.aclose()

    try:
        report = asyncio.run(execute())
    except (ValidationError, ValueError) as exc:
        print(f"benchmark configuration error: {exc}", file=sys.stderr)
        return 2
    return _finish_run(
        report,
        output=args.output,
        baseline_path=args.baseline,
        gate_enabled=args.gate,
        update=args.update_baseline,
    )


def _run_pipeline(args: argparse.Namespace) -> int:
    dataset = load_dataset("extraction", args.dataset_version)
    report = asyncio.run(
        run_pipeline_suite(
            dataset,
            database_url=args.database_url,
            git_sha=_git_sha(),
        )
    )
    return _finish_run(
        report,
        output=args.output,
        baseline_path=args.baseline,
        gate_enabled=args.gate,
        update=args.update_baseline,
    )


def _run_gate(args: argparse.Namespace) -> int:
    report = _load_report(args.report)
    gate_result = evaluate_gate(report, baseline=load_baseline(args.baseline))
    print(gate_result.render())
    return 0 if gate_result.passed else 1


def _run_update_baseline(args: argparse.Namespace) -> int:
    report = _load_report(args.report)
    update_baseline(args.baseline, report=report)
    print(f"baseline updated: {args.baseline}")
    return 0


def _load_report(path: Path) -> ExtractionRunReport | PipelineRunReport:
    payload = path.read_text(encoding="utf-8")
    try:
        return ExtractionRunReport.model_validate_json(payload)
    except ValidationError:
        return PipelineRunReport.model_validate_json(payload)


def _finish_run(
    report: ExtractionRunReport | PipelineRunReport,
    *,
    output: Path | None,
    baseline_path: Path,
    gate_enabled: bool,
    update: bool,
) -> int:
    path = output or _default_output_path(report)
    markdown_path = write_report(report, path)
    markdown = render_markdown(report)
    print(markdown)
    print(f"report: {path}")
    print(f"summary: {markdown_path}")
    _append_step_summary(markdown)

    gate_result: GateResult | None = None
    if gate_enabled:
        gate_result = evaluate_gate(report, baseline=load_baseline(baseline_path))
        print(gate_result.render())
    if update:
        update_baseline(baseline_path, report=report)
        print(f"baseline updated: {baseline_path}")
    if gate_result is not None and not gate_result.passed:
        return 1
    return 0


def _default_output_path(report: ExtractionRunReport | PipelineRunReport) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"{report.meta.suite}_{report.meta.mode}_{stamp}.json"
    return RESULTS_DIRECTORY / name


def _append_step_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(markdown)
        handle.write("\n")


def _git_sha() -> str | None:
    environment_sha = os.environ.get("GITHUB_SHA")
    if environment_sha:
        return environment_sha
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPOSITORY_ROOT,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


if __name__ == "__main__":
    raise SystemExit(main())
