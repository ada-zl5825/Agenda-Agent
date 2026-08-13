"""Thin HTTP transport for delegated Microsoft authorization."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse

from recruitment_agent.api.dependencies import (
    get_authorization_service,
    get_web_session_manager,
)
from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService
from recruitment_agent.web.security import WebSessionManager

router = APIRouter(prefix="/auth", tags=["microsoft-auth"])
AuthorizationService = Annotated[
    MicrosoftAuthorizationService,
    Depends(get_authorization_service),
]
SessionManager = Annotated[WebSessionManager, Depends(get_web_session_manager)]


@router.get("/login", response_class=RedirectResponse)
async def login(
    request: Request,
    service: AuthorizationService,
    sessions: SessionManager,
    return_to: str = "/reviews",
) -> RedirectResponse:
    result = await service.start_authorization()
    response = RedirectResponse(
        url=result.authorization_url,
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        sessions.return_cookie_name,
        sessions.issue_return_path(return_to),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=600,
        path="/auth",
    )
    return response


@router.get("/callback", response_class=RedirectResponse)
async def callback(
    request: Request,
    service: AuthorizationService,
    sessions: SessionManager,
) -> RedirectResponse:
    result = await service.complete_authorization(dict(request.query_params))
    return_path = sessions.read_return_path(
        request.cookies.get(sessions.return_cookie_name)
    )
    response = RedirectResponse(url=return_path, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        sessions.cookie_name,
        sessions.issue(result.connection_id),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=sessions.cookie_max_age,
        path="/",
    )
    response.delete_cookie(sessions.return_cookie_name, path="/auth")
    return response
