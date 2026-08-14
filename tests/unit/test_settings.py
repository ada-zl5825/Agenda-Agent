from base64 import b64encode
from uuid import uuid4

import pytest
from pydantic import ValidationError

from recruitment_agent.config.settings import (
    AzureOpenAISettings,
    LinkEncryptionSettings,
    MicrosoftSettings,
    OperationsSettings,
    Settings,
)


def test_settings_accept_phase_zero_configuration() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:password@localhost/recruitment",
        user_timezone="Europe/London",
    )

    assert settings.user_timezone == "Europe/London"
    assert "password" not in repr(settings)


def test_settings_reject_non_psycopg_database_driver() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        Settings(
            database_url="sqlite:///local.db",
            user_timezone="Europe/London",
        )


def test_settings_reject_unknown_timezone() -> None:
    with pytest.raises(ValidationError, match="valid IANA timezone"):
        Settings(
            database_url="postgresql+psycopg://user:password@localhost/recruitment",
            user_timezone="Mars/Olympus_Mons",
        )


def test_microsoft_settings_require_a_32_byte_encryption_key() -> None:
    with pytest.raises(ValidationError, match="exactly 32 bytes"):
        MicrosoftSettings(
            microsoft_client_id="client",
            microsoft_client_secret="secret",
            microsoft_redirect_uri="http://localhost:8000/auth/callback",
            microsoft_connection_id=uuid4(),
            token_cache_encryption_key=b64encode(b"too-short").decode(),
        )


def test_microsoft_settings_keep_secrets_out_of_repr() -> None:
    settings = MicrosoftSettings(
        microsoft_client_id="client",
        microsoft_client_secret="client-secret-value",
        microsoft_redirect_uri="http://localhost:8000/auth/callback",
        microsoft_connection_id=uuid4(),
        token_cache_encryption_key=b64encode(b"k" * 32).decode(),
    )

    assert "client-secret-value" not in repr(settings)
    assert b64encode(b"k" * 32).decode() not in repr(settings)


def test_phase_eight_requires_independent_web_key_when_brief_is_enabled() -> None:
    common = {
        "microsoft_client_id": "client",
        "microsoft_client_secret": "client-secret",
        "microsoft_redirect_uri": "https://agent.example/auth/callback",
        "microsoft_connection_id": uuid4(),
        "token_cache_encryption_key": b64encode(b"t" * 32).decode(),
        "daily_brief_enabled": True,
        "daily_brief_recipient": "me@example.test",
        "public_app_base_url": "https://agent.example",
    }
    with pytest.raises(ValidationError, match="WEB_SESSION_SIGNING_KEY"):
        MicrosoftSettings(**common)
    with pytest.raises(ValidationError, match="must not reuse"):
        MicrosoftSettings(
            **common,
            web_session_signing_key=b64encode(b"t" * 32).decode(),
        )

    settings = MicrosoftSettings(
        **common,
        web_session_signing_key=b64encode(b"w" * 32).decode(),
    )
    assert settings.daily_brief_recipient == "me@example.test"
    assert settings.web_session_key_bytes == b"w" * 32

    runtime_recipient = MicrosoftSettings(
        **{**common, "daily_brief_recipient": None},
        web_session_signing_key=b64encode(b"w" * 32).decode(),
    )
    assert runtime_recipient.daily_brief_recipient is None


def test_disabled_daily_brief_accepts_empty_deployment_recipient() -> None:
    settings = MicrosoftSettings(
        microsoft_client_id="client",
        microsoft_client_secret="client-secret",
        microsoft_redirect_uri="https://agent.example/auth/callback",
        microsoft_connection_id=uuid4(),
        token_cache_encryption_key=b64encode(b"t" * 32).decode(),
        daily_brief_enabled=False,
        daily_brief_recipient="",
    )

    assert settings.daily_brief_recipient is None


def test_optional_admin_identity_override_is_normalized_and_bounded() -> None:
    common = {
        "microsoft_client_id": "client",
        "microsoft_client_secret": "secret",
        "microsoft_redirect_uri": "https://agent.example/auth/callback",
        "microsoft_connection_id": uuid4(),
        "token_cache_encryption_key": b64encode(b"t" * 32).decode(),
    }

    settings = MicrosoftSettings(
        **common,
        admin_microsoft_home_account_id="  opaque-admin-id  ",
    )

    assert settings.admin_microsoft_home_account_id == "opaque-admin-id"
    with pytest.raises(ValidationError, match="ADMIN_MICROSOFT_HOME_ACCOUNT_ID"):
        MicrosoftSettings(**common, admin_microsoft_home_account_id="invalid admin")


def test_link_encryption_settings_validate_key_vault_boundary() -> None:
    settings = LinkEncryptionSettings(
        azure_key_vault_url="https://vault.example.test",
        link_encryption_key_secret_name="link-key",
        key_vault_request_timeout_seconds=5,
    )

    assert str(settings.azure_key_vault_url) == "https://vault.example.test/"
    assert settings.link_encryption_key_secret_name == "link-key"

    with pytest.raises(ValidationError, match="must not be empty"):
        LinkEncryptionSettings(
            azure_key_vault_url="https://vault.example.test",
            link_encryption_key_secret_name=" ",
        )

    with pytest.raises(ValidationError, match="must use HTTPS"):
        LinkEncryptionSettings(
            azure_key_vault_url="http://vault.example.test",
            link_encryption_key_secret_name="link-key",
        )


def test_azure_openai_settings_are_safe_when_disabled() -> None:
    settings = AzureOpenAISettings(llm_enabled=False)

    assert settings.azure_openai_endpoint is None
    assert settings.azure_openai_api_version == "2024-10-21"
    assert settings.azure_openai_max_retry_attempts == 3


def test_azure_openai_settings_require_enabled_boundary() -> None:
    with pytest.raises(ValidationError, match="required when LLM_ENABLED=true"):
        AzureOpenAISettings(llm_enabled=True)

    with pytest.raises(ValidationError, match="must use HTTPS"):
        AzureOpenAISettings(
            llm_enabled=True,
            azure_openai_endpoint="http://openai.example.test",
            azure_openai_deployment="structured-model",
        )

    settings = AzureOpenAISettings(
        llm_enabled=True,
        azure_openai_endpoint="https://openai.example.test",
        azure_openai_deployment="structured-model",
    )
    assert settings.azure_openai_deployment == "structured-model"


def test_phase_nine_a_operations_secret_and_queue_are_validated() -> None:
    token = b64encode(b"o" * 32).decode()
    settings = OperationsSettings(ops_api_token=token)

    assert settings.api_token == token
    assert token not in repr(settings)
    assert settings.ops_queue_name == "recruitment-operations"

    with pytest.raises(ValidationError, match="exactly 32 bytes"):
        OperationsSettings(ops_api_token=b64encode(b"short").decode())
    with pytest.raises(ValidationError, match="valid Azure queue name"):
        OperationsSettings(ops_api_token=token, ops_queue_name="Invalid--Queue")
