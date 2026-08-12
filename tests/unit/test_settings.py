from base64 import b64encode
from uuid import uuid4

import pytest
from pydantic import ValidationError

from recruitment_agent.config.settings import MicrosoftSettings, Settings


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
