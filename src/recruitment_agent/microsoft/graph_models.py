"""Typed Microsoft Graph wire DTOs kept inside the infrastructure adapter."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GraphEmailAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    address: str | None = None


class GraphRecipient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email_address: GraphEmailAddress | None = Field(default=None, alias="emailAddress")


class GraphItemBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content_type: str = Field(alias="contentType")
    content: str


class GraphRemoved(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str | None = None


class GraphMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    internet_message_id: str | None = Field(default=None, alias="internetMessageId")
    subject: str | None = None
    sender: GraphRecipient | None = Field(default=None, alias="from")
    received_at: datetime | None = Field(default=None, alias="receivedDateTime")
    web_link: str | None = Field(default=None, alias="webLink")
    has_attachments: bool = Field(default=False, alias="hasAttachments")
    body: GraphItemBody | None = None
    removed: GraphRemoved | None = Field(default=None, alias="@removed")


class GraphDeltaResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: list[GraphMessage]
    next_link: str | None = Field(default=None, alias="@odata.nextLink")
    delta_link: str | None = Field(default=None, alias="@odata.deltaLink")
