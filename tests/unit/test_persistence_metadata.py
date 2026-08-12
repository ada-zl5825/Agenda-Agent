from sqlalchemy import UniqueConstraint

from recruitment_agent.persistence import models as persistence_models  # noqa: F401
from recruitment_agent.persistence.base import Base


def test_phase_three_tables_use_application_schema() -> None:
    expected_tables = {
        "app.action_items",
        "app.application_status_history",
        "app.applications",
        "app.event_history",
        "app.mail_sync_states",
        "app.microsoft_authorization_flows",
        "app.microsoft_connections",
        "app.recruitment_events",
        "app.secure_links",
        "app.source_emails",
    }

    assert set(Base.metadata.tables) == expected_tables
    assert all(table.schema == "app" for table in Base.metadata.sorted_tables)


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
