"""Privacy regressions for checkpointed Phase 5 workflow state."""

from datetime import UTC, datetime
from uuid import UUID

from recruitment_agent.domain.enums import ActionType, ApplicationStatus, RecruitmentEventType
from recruitment_agent.domain.processing import (
    DomainTransitionPlan,
    EventMutationKind,
    PlannedActionItem,
    PlannedEventMutation,
)
from recruitment_agent.extraction.models import (
    ExtractionValidationResult,
    ExtractionValidationStatus,
    RecruitmentExtraction,
)
from recruitment_agent.graph.contracts import (
    CompanyResolutionEvidence,
    SafePreparedEmail,
    WorkflowExtractionResult,
    WorkflowPrefilterDecision,
)
from recruitment_agent.graph.state import RecruitmentGraphState


def test_graph_state_contract_excludes_sensitive_and_transient_fields() -> None:
    state_fields = set(RecruitmentGraphState.__annotations__)
    forbidden = {
        "raw_html",
        "raw_email_body",
        "normalized_email",
        "oauth_token",
        "refresh_token",
        "decrypted_url",
        "secure_links",
        "attachments",
        "model_prompt",
        "model_completion",
        "plaintext_url",
        "action_url",
    }

    assert state_fields.isdisjoint(forbidden)
    assert {"source_email_id", "link_refs", "sanitized_text"}.issubset(state_fields)


def test_checkpoint_safe_contract_representations_hide_sanitized_evidence() -> None:
    prepared = SafePreparedEmail(
        source_email_id=UUID("00000000-0000-0000-0000-000000000551"),
        sender_domain="example.test",
        received_at=datetime(2026, 8, 13, tzinfo=UTC),
        sanitized_text="Private Candidate [REDACTED_EMAIL] ACTION_LINK_01",
        link_refs=("ACTION_LINK_01",),
        prefilter_decision=WorkflowPrefilterDecision.LIKELY_RECRUITMENT,
    )

    assert "Private Candidate" not in repr(prepared)
    assert "ACTION_LINK_01" in repr(prepared)


def test_structured_checkpoint_result_repr_hides_company_and_role_evidence() -> None:
    extraction = RecruitmentExtraction(
        relevant=True,
        company_raw="Private Employer",
        role_raw="Private Role",
        event_type="general_update",
        interview_round=None,
        action_required=False,
        action_text=None,
        action_link_ref=None,
        event_datetime=None,
        deadline=None,
        timezone_explicit=False,
        timezone_text=None,
        source_datetime_text=None,
        source_deadline_text=None,
        meeting_platform=None,
        location=None,
        company_confidence=1.0,
        event_confidence=1.0,
        datetime_confidence=1.0,
    )
    result = WorkflowExtractionResult(
        extraction=extraction,
        validation=ExtractionValidationResult(
            status=ExtractionValidationStatus.VALID,
            issues=(),
        ),
        prompt_version="recruitment-extraction-v1",
        company=CompanyResolutionEvidence(
            raw_company_name="Private Employer",
            company_id=UUID("00000000-0000-0000-0000-000000000552"),
            status="resolved",
            method="alias_exact",
            confidence=1.0,
            matched_value="private employer",
            candidate_company_ids=(),
        ),
        role=None,
        company_resolution_audit_id=None,
    )

    representation = repr(result)
    assert "Private Employer" not in representation
    assert "Private Role" not in representation
    assert "private employer" not in representation


def test_phase_six_transition_plan_keeps_only_opaque_link_reference() -> None:
    source_email_id = UUID("00000000-0000-0000-0000-000000000553")
    application_id = UUID("00000000-0000-0000-0000-000000000554")
    event_id = UUID("00000000-0000-0000-0000-000000000555")
    action_id = UUID("00000000-0000-0000-0000-000000000556")
    plan = DomainTransitionPlan(
        source_email_id=source_email_id,
        application_id=application_id,
        create_application=True,
        company_id=UUID("00000000-0000-0000-0000-000000000557"),
        raw_company_name="Private Employer",
        role_name="Private Role",
        role_normalized="private role",
        application_status_before=ApplicationStatus.UNKNOWN,
        application_status_after=ApplicationStatus.ASSESSMENT_PENDING,
        event=PlannedEventMutation(
            kind=EventMutationKind.CREATE,
            event_id=event_id,
            type=RecruitmentEventType.ASSESSMENT,
            round=None,
            starts_at=None,
            deadline_at=datetime(2026, 8, 20, tzinfo=UTC),
            timezone="Europe/London",
            source_datetime_text="private deadline evidence",
            semantic_fingerprint="a" * 64,
        ),
        action_item=PlannedActionItem(
            id=action_id,
            type=ActionType.ASSESSMENT,
            title="Private assessment action",
            due_at=datetime(2026, 8, 20, tzinfo=UTC),
            secure_link_ref="ACTION_LINK_01",
            idempotency_key="b" * 64,
        ),
    )

    representation = repr(plan)
    checkpoint_json = plan.model_dump_json()
    assert "Private Employer" not in representation
    assert "Private Role" not in representation
    assert "Private assessment action" not in representation
    assert "private deadline evidence" not in representation
    assert "ACTION_LINK_01" in checkpoint_json
    assert "https://" not in checkpoint_json
    assert "decrypted_url" not in checkpoint_json
