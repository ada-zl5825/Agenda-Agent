"""Thin HTTP transport for delegated Microsoft authorization."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from recruitment_agent.api.dependencies import get_authorization_service
from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService

router = APIRouter(prefix="/auth", tags=["microsoft-auth"])
AuthorizationService = Annotated[
    MicrosoftAuthorizationService,
    Depends(get_authorization_service),
]


class AuthorizationCompletedResponse(BaseModel):
    status: str = "authorized"
    connection_id: UUID


@router.get("/login", response_class=RedirectResponse)
async def login(service: AuthorizationService) -> RedirectResponse:
    result = await service.start_authorization()
    return RedirectResponse(
        url=result.authorization_url,
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/callback", response_model=AuthorizationCompletedResponse)
async def callback(
    request: Request,
    service: AuthorizationService,
) -> AuthorizationCompletedResponse:
    result = await service.complete_authorization(dict(request.query_params))
    return AuthorizationCompletedResponse(connection_id=result.connection_id)
