"""Golden dataset hygiene: every case must replay cleanly through the validator."""

import pytest

from benchmarks.harness.loader import load_dataset
from benchmarks.harness.models import BenchmarkCase, PipelineOutcome
from benchmarks.harness.scorers import score_extraction_case
from recruitment_agent.extraction.models import RecruitmentExtractionRequest
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_VERSION
from recruitment_agent.extraction.validator import ExtractionValidator

DATASET = load_dataset("extraction", "v1")


def test_dataset_shape() -> None:
    assert DATASET.manifest.case_count == 60
    assert len(DATASET.cases) == 60
    assert DATASET.manifest.prompt_version == RECRUITMENT_EXTRACTION_PROMPT_VERSION


def test_case_source_email_ids_are_unique() -> None:
    ids = {case.source_email_id for case in DATASET.cases}
    assert len(ids) == len(DATASET.cases)


def test_completed_pipeline_companies_are_seeded() -> None:
    """A completed workflow requires deterministic company resolution."""
    seeded = {spec.canonical_name for spec in DATASET.companies}
    for case in DATASET.cases:
        domain = case.expected_domain
        if (
            domain is not None
            and domain.outcome is PipelineOutcome.COMPLETED
            and case.recorded_response.company_raw is not None
        ):
            assert case.recorded_response.company_raw in seeded, case.case_id


@pytest.mark.parametrize("case", DATASET.cases, ids=lambda case: case.case_id)
def test_recorded_response_replays_to_expected_labels(case: BenchmarkCase) -> None:
    request = RecruitmentExtractionRequest(
        source_email_id=case.source_email_id,
        received_at=case.input.received_at,
        sanitized_text=case.input.sanitized_text,
        allowed_link_refs=case.input.allowed_link_refs,
        prompt_version=RECRUITMENT_EXTRACTION_PROMPT_VERSION,
    )
    validation = ExtractionValidator().validate(case.recorded_response, request)
    result = score_extraction_case(
        case,
        extraction=case.recorded_response,
        validation=validation,
    )

    assert result.succeeded
    mismatched = sorted(name for name, ok in result.field_matches.items() if not ok)
    assert not mismatched, f"golden labels disagree with recorded response: {mismatched}"
    assert result.validation_status_match, (
        result.expected_validation_status,
        result.actual_validation_status,
    )
    assert result.validation_issues_match, [issue.code.value for issue in validation.issues]
    assert not result.missed_review
