"""Pipeline harness seeds placeholder links and sanitizes workflow failures."""

from uuid import uuid4

from benchmarks.harness.extraction_suite import _invocation_error_label
from benchmarks.harness.pipeline_suite import (
    placeholder_secure_link_rows,
    sanitized_workflow_failure,
)
from recruitment_agent.application.errors import ExtractionInvocationError


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
