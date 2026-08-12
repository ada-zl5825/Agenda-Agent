"""Privacy-safe contracts for URL discovery and sanitized model-ready text."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class UrlSource(StrEnum):
    HTML_LINK = "html_link"
    PLAIN_TEXT = "plain_text"


class DiscoveredUrl(BaseModel):
    """Short-lived raw URL. SecretStr prevents accidental repr/log disclosure."""

    model_config = ConfigDict(frozen=True)

    ordinal: int = Field(ge=1)
    url: SecretStr
    domain: str
    display_text: str | None = Field(default=None, repr=False)
    source: UrlSource


class SanitizedContent(BaseModel):
    """The only email-body text contract allowed across a future model boundary."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(repr=False)
    redaction_counts: dict[str, int]
