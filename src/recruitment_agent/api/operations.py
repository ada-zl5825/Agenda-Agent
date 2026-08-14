"""Protected, thin HTTP adapter for Phase 9A operational commands."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from recruitment_agent.application.operations import (
    ControlReason,
    OperationsControlService,
    OperationSnapshot,
    OperationStatus,
    OperationType,
    RuntimeControl,
    RuntimeControlPatch,
)
from recruitment_agent.config import get_operations_settings
from recruitment_agent.jobs.operations import operations_control_service
from recruitment_agent.operations.security import OperationsTokenAuthenticator

router = APIRouter(tags=["operations"])
bearer = HTTPBearer(auto_error=False)


async def authorize_operations(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    token = None if credentials is None else credentials.credentials
    OperationsTokenAuthenticator(get_operations_settings().api_token).authenticate(token)


async def get_operations_service() -> AsyncIterator[OperationsControlService]:
    async with operations_control_service() as service:
        yield service


Authorized = Annotated[None, Depends(authorize_operations)]
Service = Annotated[OperationsControlService, Depends(get_operations_service)]
IdempotencyKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=8, max_length=128, pattern=r"^[!-~]+$"),
    Header(alias="Idempotency-Key"),
]


class RuntimeControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    mail_sync_enabled: bool
    workflow_enabled: bool
    calendar_write_enabled: bool
    daily_brief_enabled: bool
    version: int
    reason: ControlReason
    updated_by: str
    updated_at: datetime


class RuntimeControlUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: ControlReason
    mail_sync_enabled: bool | None = None
    workflow_enabled: bool | None = None
    calendar_write_enabled: bool | None = None
    daily_brief_enabled: bool | None = None

    @model_validator(mode="after")
    def require_switch(self) -> RuntimeControlUpdateRequest:
        if all(
            value is None
            for value in (
                self.mail_sync_enabled,
                self.workflow_enabled,
                self.calendar_write_enabled,
                self.daily_brief_enabled,
            )
        ):
            raise ValueError("at least one runtime switch is required")
        return self


class OperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    operation_type: OperationType
    status: OperationStatus
    source_email_id: UUID | None
    batch_limit: int | None
    parent_operation_id: UUID | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    result: dict[str, str | int | bool | None] | None
    error_code: str | None


class BatchRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)


class ReadinessResponse(BaseModel):
    status: str
    database_ready: bool
    oauth_authorized: bool


class StatusResponse(BaseModel):
    control: RuntimeControlResponse
    capabilities: dict[str, bool]
    oauth_authorized: bool
    mail_sync: dict[str, object]
    source_email_counts: dict[str, int]
    workflow_counts: dict[str, int]
    open_review_count: int
    operation_counts: dict[str, int]
    latest_brief_status: str | None
    latest_brief_date: str | None


def _control_response(control: RuntimeControl) -> RuntimeControlResponse:
    return RuntimeControlResponse.model_validate(control)


def _operation_response(operation: OperationSnapshot) -> OperationResponse:
    return OperationResponse.model_validate(operation)


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(_authorized: Authorized, service: Service, response: Response) -> object:
    snapshot = await service.get_readiness()
    if not snapshot.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if snapshot.ready else "not_ready",
        database_ready=snapshot.database_ready,
        oauth_authorized=snapshot.oauth_authorized,
    )


@router.get("/api/v1/ops/control", response_model=RuntimeControlResponse)
async def get_control(_authorized: Authorized, service: Service) -> RuntimeControlResponse:
    return _control_response(await service.get_control())


@router.patch("/api/v1/ops/control", response_model=RuntimeControlResponse)
async def update_control(
    request: RuntimeControlUpdateRequest,
    _authorized: Authorized,
    service: Service,
) -> RuntimeControlResponse:
    return _control_response(
        await service.update_control(RuntimeControlPatch(**request.model_dump()))
    )


@router.get("/api/v1/ops/status", response_model=StatusResponse)
async def get_status(_authorized: Authorized, service: Service) -> StatusResponse:
    snapshot = await service.get_status()
    mail_sync: dict[str, object] = {
        "status": None if snapshot.mail_sync.status is None else snapshot.mail_sync.status.value,
        "cursor_present": snapshot.mail_sync.cursor_present,
        "last_started_at": snapshot.mail_sync.last_started_at,
        "last_finished_at": snapshot.mail_sync.last_finished_at,
        "error_code": snapshot.mail_sync.error_code,
    }
    return StatusResponse(
        control=_control_response(snapshot.control),
        capabilities={
            "workflow_processing_available": (
                snapshot.capabilities.workflow_processing_available
            ),
            "calendar_write_available": snapshot.capabilities.calendar_write_available,
            "daily_brief_available": snapshot.capabilities.daily_brief_available,
        },
        oauth_authorized=snapshot.oauth_authorized,
        mail_sync=mail_sync,
        source_email_counts=snapshot.source_email_counts,
        workflow_counts=snapshot.workflow_counts,
        open_review_count=snapshot.open_review_count,
        operation_counts=snapshot.operation_counts,
        latest_brief_status=snapshot.latest_brief_status,
        latest_brief_date=snapshot.latest_brief_date,
    )


async def _submit(
    service: OperationsControlService,
    *,
    operation_type: OperationType,
    idempotency_key: str,
    source_email_id: UUID | None = None,
    batch_limit: int | None = None,
) -> OperationResponse:
    return _operation_response(
        await service.submit(
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            source_email_id=source_email_id,
            batch_limit=batch_limit,
        )
    )


@router.post(
    "/api/v1/ops/operations/mail-sync",
    response_model=OperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_mail_sync(
    _authorized: Authorized,
    service: Service,
    idempotency_key: IdempotencyKey,
) -> OperationResponse:
    return await _submit(
        service,
        operation_type=OperationType.MAIL_SYNC,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/api/v1/ops/operations/process-email/{source_email_id}",
    response_model=OperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_process_email(
    source_email_id: UUID,
    _authorized: Authorized,
    service: Service,
    idempotency_key: IdempotencyKey,
) -> OperationResponse:
    return await _submit(
        service,
        operation_type=OperationType.PROCESS_EMAIL,
        idempotency_key=idempotency_key,
        source_email_id=source_email_id,
    )


@router.post(
    "/api/v1/ops/operations/process-pending",
    response_model=OperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_process_pending(
    request: BatchRequest,
    _authorized: Authorized,
    service: Service,
    idempotency_key: IdempotencyKey,
) -> OperationResponse:
    return await _submit(
        service,
        operation_type=OperationType.PROCESS_PENDING,
        idempotency_key=idempotency_key,
        batch_limit=request.limit,
    )


@router.post(
    "/api/v1/ops/operations/reset-mail-cursor",
    response_model=OperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_cursor_reset(
    _authorized: Authorized,
    service: Service,
    idempotency_key: IdempotencyKey,
) -> OperationResponse:
    return await _submit(
        service,
        operation_type=OperationType.RESET_MAIL_CURSOR,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/api/v1/ops/operations/{operation_id}",
    response_model=OperationResponse,
)
async def get_operation(
    operation_id: UUID,
    _authorized: Authorized,
    service: Service,
) -> OperationResponse:
    return _operation_response(await service.get_operation(operation_id))
