"""Environment-backed settings with deterministic validation."""

from base64 import b64decode
from binascii import Error as Base64Error
from enum import StrEnum
from functools import lru_cache
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
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


class MicrosoftSettings(BaseSettings):
    """Phase 1 Microsoft Graph, OAuth, and mail synchronization settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    microsoft_client_id: str
    microsoft_client_secret: SecretStr = Field(repr=False)
    microsoft_tenant: str = "consumers"
    microsoft_redirect_uri: AnyHttpUrl
    microsoft_connection_id: UUID

    token_cache_encryption_key: SecretStr = Field(repr=False)
    token_cache_encryption_key_version: str = "v1"

    graph_base_url: AnyHttpUrl = AnyHttpUrl("https://graph.microsoft.com/v1.0")
    graph_request_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    graph_max_retry_attempts: int = Field(default=4, ge=1, le=10)
    graph_max_retry_delay_seconds: float = Field(default=30.0, gt=0, le=300)

    mail_folder_id: str = "inbox"
    mail_sync_enabled: bool = True
    mail_sync_interval_minutes: int = Field(default=10, ge=1, le=1440)

    @field_validator("microsoft_client_id", "mail_folder_id", "token_cache_encryption_key_version")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "value must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("microsoft_tenant")
    @classmethod
    def validate_tenant(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "MICROSOFT_TENANT must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("token_cache_encryption_key")
    @classmethod
    def validate_token_cache_key(cls, value: SecretStr) -> SecretStr:
        try:
            decoded = b64decode(value.get_secret_value(), validate=True)
        except (Base64Error, ValueError) as exc:
            msg = "TOKEN_CACHE_ENCRYPTION_KEY must be valid base64"
            raise ValueError(msg) from exc
        if len(decoded) != 32:
            msg = "TOKEN_CACHE_ENCRYPTION_KEY must decode to exactly 32 bytes"
            raise ValueError(msg)
        return value

    @property
    def authority(self) -> str:
        """Return the configured Microsoft identity authority URL."""
        return f"https://login.microsoftonline.com/{self.microsoft_tenant}"

    @property
    def token_cache_key_bytes(self) -> bytes:
        """Decode the validated AES-256 token-cache key."""
        return b64decode(self.token_cache_encryption_key.get_secret_value(), validate=True)


@lru_cache(maxsize=1)
def get_microsoft_settings() -> MicrosoftSettings:
    """Load Phase 1 settings only at a Microsoft integration boundary."""
    return MicrosoftSettings()
