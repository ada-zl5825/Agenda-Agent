"""Environment-backed settings with deterministic validation."""

from base64 import b64decode
from binascii import Error as Base64Error
from enum import StrEnum
from functools import lru_cache
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
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
    calendar_sync_enabled: bool = False
    calendar_interview_placeholder_minutes: int = Field(default=60, ge=1, le=1440)
    calendar_assessment_placeholder_minutes: int = Field(default=30, ge=1, le=1440)
    daily_brief_enabled: bool = False
    daily_brief_recipient: str | None = None
    daily_brief_schedule: str = "0 0 * * * *"
    daily_brief_local_hour: int = Field(default=8, ge=0, le=23)
    public_app_base_url: AnyHttpUrl | None = None
    web_session_signing_key: SecretStr | None = Field(default=None, repr=False)
    web_session_ttl_seconds: int = Field(default=28_800, ge=300, le=86_400)

    @field_validator(
        "microsoft_client_id",
        "mail_folder_id",
        "token_cache_encryption_key_version",
        "daily_brief_schedule",
    )
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

    @field_validator("web_session_signing_key")
    @classmethod
    def validate_web_session_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            decoded = b64decode(value.get_secret_value(), validate=True)
        except (Base64Error, ValueError) as exc:
            raise ValueError("WEB_SESSION_SIGNING_KEY must be valid base64") from exc
        if len(decoded) != 32:
            raise ValueError("WEB_SESSION_SIGNING_KEY must decode to exactly 32 bytes")
        return value

    @field_validator("daily_brief_recipient", mode="before")
    @classmethod
    def normalize_optional_recipient(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_phase_eight_settings(self) -> "MicrosoftSettings":
        if self.daily_brief_enabled and (
            self.daily_brief_recipient is None
            or self.public_app_base_url is None
            or self.web_session_signing_key is None
        ):
            raise ValueError(
                "DAILY_BRIEF_RECIPIENT, PUBLIC_APP_BASE_URL, and "
                "WEB_SESSION_SIGNING_KEY are required when enabled"
            )
        if (
            self.web_session_signing_key is not None
            and b64decode(
                self.web_session_signing_key.get_secret_value(),
                validate=True,
            )
            == b64decode(
                self.token_cache_encryption_key.get_secret_value(),
                validate=True,
            )
        ):
            raise ValueError(
                "WEB_SESSION_SIGNING_KEY must not reuse TOKEN_CACHE_ENCRYPTION_KEY"
            )
        if self.daily_brief_recipient is not None:
            recipient = self.daily_brief_recipient.strip()
            if "@" not in recipient or any(char.isspace() for char in recipient):
                raise ValueError("DAILY_BRIEF_RECIPIENT must be an email address")
            self.daily_brief_recipient = recipient
        return self

    @property
    def authority(self) -> str:
        """Return the configured Microsoft identity authority URL."""
        return f"https://login.microsoftonline.com/{self.microsoft_tenant}"

    @property
    def token_cache_key_bytes(self) -> bytes:
        """Decode the validated AES-256 token-cache key."""
        return b64decode(self.token_cache_encryption_key.get_secret_value(), validate=True)

    @property
    def web_session_key_bytes(self) -> bytes:
        if self.web_session_signing_key is None:
            raise ValueError("WEB_SESSION_SIGNING_KEY is required for authenticated web routes")
        return b64decode(self.web_session_signing_key.get_secret_value(), validate=True)


@lru_cache(maxsize=1)
def get_microsoft_settings() -> MicrosoftSettings:
    """Load Phase 1 settings only at a Microsoft integration boundary."""
    return MicrosoftSettings()


class LinkEncryptionSettings(BaseSettings):
    """Phase 3 Azure Key Vault configuration for secure action URLs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    azure_key_vault_url: AnyHttpUrl
    link_encryption_key_secret_name: str
    key_vault_request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    @field_validator("azure_key_vault_url")
    @classmethod
    def validate_vault_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("AZURE_KEY_VAULT_URL must use HTTPS")
        return value

    @field_validator("link_encryption_key_secret_name")
    @classmethod
    def validate_secret_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("LINK_ENCRYPTION_KEY_SECRET_NAME must not be empty")
        return normalized


@lru_cache(maxsize=1)
def get_link_encryption_settings() -> LinkEncryptionSettings:
    """Load Key Vault configuration only at the secure-link boundary."""
    return LinkEncryptionSettings()


class AzureOpenAISettings(BaseSettings):
    """Phase 4 Azure OpenAI structured-extraction configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_enabled: bool = False
    azure_openai_endpoint: AnyHttpUrl | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_request_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    azure_openai_max_retry_attempts: int = Field(default=3, ge=1, le=5)

    @field_validator("azure_openai_endpoint")
    @classmethod
    def validate_openai_endpoint(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and value.scheme != "https":
            raise ValueError("AZURE_OPENAI_ENDPOINT must use HTTPS")
        return value

    @field_validator("azure_openai_deployment", "azure_openai_api_version")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_enabled_configuration(self) -> "AzureOpenAISettings":
        if self.llm_enabled and (
            self.azure_openai_endpoint is None or self.azure_openai_deployment is None
        ):
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT are required "
                "when LLM_ENABLED=true"
            )
        if self.azure_openai_api_version is None:
            raise ValueError("AZURE_OPENAI_API_VERSION must not be empty")
        return self


@lru_cache(maxsize=1)
def get_azure_openai_settings() -> AzureOpenAISettings:
    """Load Phase 4 settings only at the model integration boundary."""
    return AzureOpenAISettings()
