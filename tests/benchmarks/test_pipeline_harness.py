"""Pipeline harness seeds placeholder links and sanitizes workflow failures."""

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from benchmarks.harness.extraction_suite import _invocation_error_label
from benchmarks.harness.pipeline_suite import (
    placeholder_secure_link_rows,
    sanitized_workflow_failure,
    seed_pipeline_case_rows,
)
from recruitment_agent.application.errors import ExtractionInvocationError


class _RecordingSession:
    """Capture merge/flush/add order without opening a database."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def merge(self, obj: object) -> object:
        self.calls.append(f"merge:{type(obj).__name__}")
        return obj

    async def flush(self) -> None:
        self.calls.append("flush")

    def add(self, obj: object) -> None:
        self.calls.append(f"add:{type(obj).__name__}")


@pytest.mark.asyncio
async def test_seed_pipeline_case_rows_flushes_source_email_before_links() -> None:
    session = _RecordingSession()

    await seed_pipeline_case_rows(
        cast(AsyncSession, session),
        source_email_id=uuid4(),
        case_id="assessment_en_bst_deadline_link",
        sender_domain="example.com",
        received_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
        link_refs=("ACTION_LINK_01", "ACTION_LINK_02"),
    )

    assert session.calls[0] == "merge:SourceEmailModel"
    assert session.calls[1] == "flush"
    assert session.calls[2:] == ["add:SecureLinkModel", "add:SecureLinkModel"]


def test_placeholder_secure_links_contain_no_url_bytes() -> None:
    source_email_id = uuid4()
    rows = placeholder_secure_link_rows(
        source_email_id=source_email_id,
        link_refs=("ACTION_LINK_01", "ACTION_LINK_02"),
    )

    assert [row.ref for row in rows] == ["ACTION_LINK_01", "ACTION_LINK_02"]
    assert {row.source_email_id for row in rows} == {source_email_id}
    for row in rows:
        assert b"http" not in row.encrypted_url
        assert b"://" not in row.encrypted_url
        assert row.domain == "benchmark.example"


def test_sanitized_workflow_failure_omits_url_material() -> None:
    safe = sanitized_workflow_failure(ValueError("action link reference does not resolve"))
    leaked = sanitized_workflow_failure(ValueError("see https://secret.example/token"))

    assert safe == "workflow raised ValueError: action link reference does not resolve"
    assert leaked == "workflow raised ValueError"
    assert "https://" not in leaked


def test_invocation_error_label_keeps_sanitized_provider_token() -> None:
    labeled = ExtractionInvocationError(
        "structured extraction failed (AuthenticationError:401)",
        provider_failure="AuthenticationError:401",
    )
    dirty = ExtractionInvocationError(
        "structured extraction failed",
        provider_failure="https://example.test",
    )

    assert _invocation_error_label(labeled) == "invocation_error:AuthenticationError:401"
    assert _invocation_error_label(dirty) == "invocation_error"
    assert _invocation_error_label(ExtractionInvocationError()) == "invocation_error"
