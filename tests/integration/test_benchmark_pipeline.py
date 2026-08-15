"""Full L2 pipeline benchmark as a gated integration regression test."""

import os

import pytest

from benchmarks.harness.loader import load_dataset
from benchmarks.harness.pipeline_suite import run_pipeline_suite

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 on a Docker-enabled host",
    ),
]


@pytest.mark.asyncio
async def test_pipeline_suite_reaches_expected_domain_state() -> None:
    report = await run_pipeline_suite(load_dataset("extraction", "v1"))

    failing = [
        f"{case.case_id}: expected={case.expected_outcome} "
        f"actual={case.actual_outcome} {case.mismatches}"
        for case in report.cases
        if not case.passed
    ]
    assert not failing, failing
    assert report.aggregate.pass_rate == 1.0
    assert report.aggregate.checkpoint_privacy_violations == 0
