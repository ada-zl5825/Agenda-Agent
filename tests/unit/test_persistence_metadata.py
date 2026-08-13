from sqlalchemy import UniqueConstraint

from recruitment_agent.persistence import models as persistence_models  # noqa: F401
from recruitment_agent.persistence.base import Base


def test_phase_four_five_tables_use_application_schema() -> None:
    expected_tables = {
        "app.action_items",
        "app.application_status_history",
        "app.applications",
        "app.companies",
        "app.company_aliases",
        "app.company_domains",
        "app.company_resolution_attempts",
        "app.company_resolution_candidates",
        "app.event_history",
        "app.mail_sync_states",
        "app.microsoft_authorization_flows",
        "app.microsoft_connections",
        "app.llm_extractions",
        "app.processing_runs",
        "app.recruitment_events",
        "app.review_items",
        "app.secure_links",
        "app.source_emails",
    }

    assert set(Base.metadata.tables) == expected_tables
    assert all(table.schema == "app" for table in Base.metadata.sorted_tables)


def test_application_company_identity_uses_company_id_and_raw_evidence() -> None:
    applications = Base.metadata.tables["app.applications"]

    assert "company_id" in applications.c
    assert "raw_company_name" in applications.c
    assert "company_name" not in applications.c
    assert "company_normalized" not in applications.c
    company_foreign_key = next(iter(applications.c.company_id.foreign_keys))
    assert company_foreign_key.target_fullname == "app.companies.id"
    assert company_foreign_key.ondelete == "RESTRICT"


def test_idempotency_constraints_are_named_and_present() -> None:
    event_constraints = {
        constraint.name
        for constraint in Base.metadata.tables["app.recruitment_events"].constraints
        if isinstance(constraint, UniqueConstraint)
    }
    action_constraints = {
        constraint.name
        for constraint in Base.metadata.tables["app.action_items"].constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_recruitment_events_application_fingerprint" in event_constraints
    assert "uq_action_items_application_idempotency_key" in action_constraints


def test_action_items_reference_secure_links_without_cascading_deletes() -> None:
    secure_link_foreign_key = next(
        iter(Base.metadata.tables["app.action_items"].c.secure_link_id.foreign_keys)
    )

    assert secure_link_foreign_key.target_fullname == "app.secure_links.id"
    assert secure_link_foreign_key.ondelete == "SET NULL"


def test_phase_six_mutations_reference_their_source_email_evidence() -> None:
    history = Base.metadata.tables["app.application_status_history"]
    event_history = Base.metadata.tables["app.event_history"]
    actions = Base.metadata.tables["app.action_items"]

    application_source = next(iter(history.c.source_email_id.foreign_keys))
    event_source = next(iter(event_history.c.source_email_id.foreign_keys))
    action_source = next(iter(actions.c.source_email_id.foreign_keys))
    assert application_source.target_fullname == "app.source_emails.id"
    assert application_source.ondelete == "SET NULL"
    assert event_source.target_fullname == "app.source_emails.id"
    assert event_source.ondelete == "SET NULL"
    assert action_source.target_fullname == "app.source_emails.id"
    assert action_source.ondelete == "CASCADE"


def test_company_resolution_audit_references_email_and_reviewed_candidates() -> None:
    attempts = Base.metadata.tables["app.company_resolution_attempts"]
    candidates = Base.metadata.tables["app.company_resolution_candidates"]

    source_foreign_key = next(iter(attempts.c.source_email_id.foreign_keys))
    assert source_foreign_key.target_fullname == "app.source_emails.id"
    assert source_foreign_key.ondelete == "CASCADE"
    assert attempts.c.raw_company_name.type.__class__.__name__ == "Text"
    assert candidates.primary_key.columns.keys() == [
        "resolution_attempt_id",
        "company_id",
    ]


def test_phase_five_audit_tables_exclude_raw_content_and_checkpoint_payloads() -> None:
    runs = Base.metadata.tables["app.processing_runs"]
    extractions = Base.metadata.tables["app.llm_extractions"]
    reviews = Base.metadata.tables["app.review_items"]
    all_columns = set(runs.c) | set(extractions.c) | set(reviews.c)
    names = {column.name for column in all_columns}

    assert {
        "raw_html",
        "raw_email_body",
        "oauth_token",
        "decrypted_url",
        "checkpoint_payload",
        "attachments",
        "model_prompt",
        "model_completion",
    }.isdisjoint(names)
    assert "extraction" in extractions.c
    assert "validation" in extractions.c
    assert "allowed_choices" in reviews.c
    assert "resolution" in reviews.c
