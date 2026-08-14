"""Regression: review resume must honor the runtime calendar kill switch."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

import recruitment_agent.jobs.mail_processing as mail_processing_jobs
from recruitment_agent.graph.contracts import ReviewDecision


@pytest.mark.asyncio
async def test_resume_reads_the_database_calendar_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_flags: list[bool | None] = []
    resumed: list[dict[str, object]] = []

    class Runner:
        async def resume(self, **kwargs: object) -> str:
            resumed.append(dict(kwargs))
            return "resumed"

    @asynccontextmanager
    async def fake_runner(
        *,
        calendar_write_enabled: bool | None = None,
    ) -> AsyncIterator[Runner]:
        captured_flags.append(calendar_write_enabled)
        yield Runner()

    async def paused_control() -> bool:
        return False

    monkeypatch.setattr(
        mail_processing_jobs,
        "_production_workflow_runner",
        fake_runner,
    )
    monkeypatch.setattr(
        mail_processing_jobs,
        "read_calendar_write_control",
        paused_control,
    )

    result = await mail_processing_jobs.resume_mail_processing_job(
        processing_run_id=uuid4(),
        source_email_id=uuid4(),
        decision=ReviewDecision(choice="ignore"),
    )

    assert result == "resumed"
    # The paused runtime switch must reach the composition boundary; the old
    # behavior passed None, which silently re-enabled calendar writes.
    assert captured_flags == [False]
    assert len(resumed) == 1
