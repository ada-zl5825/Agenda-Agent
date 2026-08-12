"""Environment-backed settings with deterministic validation."""

from enum import StrEnum
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """Supported runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Allowed structured logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Phase 0 settings.

    External-integration settings are introduced only in their owning phase.
    Database URLs are excluded from representations to reduce accidental secret
    disclosure in tracebacks and debug output.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    database_url: str = Field(repr=False)
    user_timezone: str = "Europe/London"
    log_level: LogLevel = LogLevel.INFO

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            msg = "DATABASE_URL must use the postgresql+psycopg driver"
            raise ValueError(msg)
        return value

    @field_validator("user_timezone")
    @classmethod
    def validate_user_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            msg = "USER_TIMEZONE must be a valid IANA timezone"
            raise ValueError(msg) from exc
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache process configuration at the composition boundary."""
    return Settings()
