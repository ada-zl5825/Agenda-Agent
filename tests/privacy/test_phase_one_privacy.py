from recruitment_agent.persistence import models as persistence_models  # noqa: F401
from recruitment_agent.persistence.base import Base


def test_source_email_schema_cannot_persist_raw_content_or_attachments() -> None:
    columns = set(Base.metadata.tables["app.source_emails"].columns.keys())

    assert {"body", "raw_body", "raw_html", "attachment", "attachments"}.isdisjoint(columns)
    assert {"subject", "sender_domain", "body_hash", "has_attachments"} <= columns


def test_token_cache_schema_requires_ciphertext_and_nonce_fields() -> None:
    columns = set(Base.metadata.tables["app.microsoft_connections"].columns.keys())

    assert "access_token" not in columns
    assert "refresh_token" not in columns
    assert {"token_cache_ciphertext", "token_cache_nonce", "token_cache_key_version"} <= columns
