from dataclasses import fields

from recruitment_agent.application.agent_console import AgentConsoleSnapshot
from recruitment_agent.application.operations import (
    OperationSnapshot,
    OperationsStatusSnapshot,
    ReadinessSnapshot,
    RuntimeControl,
)


def test_agent_console_read_models_exclude_sensitive_mail_and_auth_fields() -> None:
    forbidden = {
        "access_token",
        "refresh_token",
        "ops_api_token",
        "message_id",
        "subject",
        "body",
        "raw_html",
        "secure_url",
        "decrypted_url",
        "checkpoint",
        "prompt",
        "completion",
    }
    models = (
        AgentConsoleSnapshot,
        OperationsStatusSnapshot,
        OperationSnapshot,
        ReadinessSnapshot,
        RuntimeControl,
    )

    for model in models:
        assert forbidden.isdisjoint(field.name for field in fields(model))

    assert "daily_brief_recipient" in {field.name for field in fields(RuntimeControl)}
