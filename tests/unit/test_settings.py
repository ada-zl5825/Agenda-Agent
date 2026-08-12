import pytest
from pydantic import ValidationError

from recruitment_agent.config.settings import Settings


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
