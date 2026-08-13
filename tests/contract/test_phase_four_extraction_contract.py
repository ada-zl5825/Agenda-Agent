"""Contract fixtures for the Phase 4 structured extraction boundary."""

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from recruitment_agent.extraction.models import (
    ExtractionValidationStatus,
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_VERSION
from recruitment_agent.extraction.validator import ExtractionValidator

FIXTURE_DIR = Path("tests/fixtures/extraction")
FIXTURES = tuple(sorted(FIXTURE_DIR.glob("*.json")))


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=lambda path: path.stem)
def test_extraction_fixture_contract(fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    extraction = RecruitmentExtraction.model_validate(fixture["response"])
    request = RecruitmentExtractionRequest(
        source_email_id=UUID("00000000-0000-0000-0000-000000000401"),
        received_at=datetime.fromisoformat(fixture["received_at"]),
        sanitized_text=fixture["sanitized_text"],
        allowed_link_refs=tuple(fixture["allowed_link_refs"]),
        prompt_version=RECRUITMENT_EXTRACTION_PROMPT_VERSION,
    )

    result = ExtractionValidator().validate(extraction, request)

    assert result.status is ExtractionValidationStatus(fixture["expected_status"])
    assert [issue.code.value for issue in result.issues] == fixture["expected_issues"]


def test_contract_suite_covers_all_required_phase_four_scenarios() -> None:
    names = {path.stem for path in FIXTURES}

    assert names == {
        "assessment",
        "general_update",
        "interview",
        "interview_without_timezone",
        "non_recruitment",
        "offer",
        "rejection",
        "relative_datetime",
        "reschedule",
    }


def test_structured_schema_requires_every_key_and_excludes_company_identity() -> None:
    schema = RecruitmentExtraction.model_json_schema()
    properties = schema["properties"]

    assert set(schema["required"]) == set(properties)
    assert "company_raw" in properties
    assert "role_raw" in properties
    assert "company_id" not in properties
    assert "company_normalized" not in properties
