"""Thin HTTP transport for delegated Microsoft authorization."""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse

from recruitment_agent.api.dependencies import (
    get_authorization_service,
    get_web_session_manager,
)
from recruitment_agent.application.errors import ReviewAuthenticationError
from recruitment_agent.config.settings import AppEnvironment
from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService
from recruitment_agent.microsoft.auth_contracts import AuthorizationPurpose
from recruitment_agent.web.security import WebSessionManager

router = APIRouter(prefix="/auth", tags=["microsoft-auth"])
AuthorizationService = Annotated[
    MicrosoftAuthorizationService,
    Depends(get_authorization_service),
]
SessionManager = Annotated[WebSessionManager, Depends(get_web_session_manager)]


def _secure_cookie(request: Request) -> bool:
    """Never issue an insecure session cookie from a production deployment,
    even when a proxy presents the request as plain HTTP."""
    if os.getenv("APP_ENV", "").strip().lower() == AppEnvironment.PRODUCTION.value:
        return True
    return request.url.scheme == "https"


@router.get("/login", response_class=RedirectResponse)
async def login(
    request: Request,
    service: AuthorizationService,
    sessions: SessionManager,
    return_to: str = "/agent",
) -> RedirectResponse:
    result = await service.start_admin_authorization()
    response = RedirectResponse(
        url=result.authorization_url,
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        sessions.return_cookie_name,
        sessions.issue_return_path(return_to),
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        max_age=600,
        path="/auth",
    )
    return response


@router.get("/mailbox/connect", response_class=RedirectResponse)
async def connect_mailbox(
    request: Request,
    service: AuthorizationService,
    sessions: SessionManager,
    return_to: str = "/agent",
) -> RedirectResponse:
    """Start an explicit Outlook connection change from an admin session."""
    token = request.cookies.get(sessions.cookie_name)
    try:
        session = sessions.authenticate(token)
    except ReviewAuthenticationError:
        return RedirectResponse(
            url="/auth/login?return_to=/agent",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    result = await service.start_mailbox_authorization(
        initiated_by=session.admin_home_account_id,
    )
    response = RedirectResponse(
        url=result.authorization_url,
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        sessions.return_cookie_name,
        sessions.issue_return_path(return_to),
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        max_age=600,
        path="/auth",
    )
    return response


@router.post("/logout", response_class=RedirectResponse)
async def logout(sessions: SessionManager) -> RedirectResponse:
    """Drop the signed browser session so a shared machine can be released."""
    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(sessions.cookie_name, path="/")
    return response


@router.get("/callback", response_class=RedirectResponse)
async def callback(
    request: Request,
    service: AuthorizationService,
    sessions: SessionManager,
) -> RedirectResponse:
    session_token = request.cookies.get(sessions.cookie_name)
    try:
        existing_session = sessions.authenticate(session_token)
        admin_home_account_id: str | None = existing_session.admin_home_account_id
    except ReviewAuthenticationError:
        admin_home_account_id = None
    result = await service.complete_authorization(
        dict(request.query_params),
        admin_home_account_id=admin_home_account_id,
    )
    return_path = sessions.read_return_path(
        request.cookies.get(sessions.return_cookie_name)
    )
    target = (
        f"{return_path}?notice=mailbox-connected"
        if result.purpose is AuthorizationPurpose.MAILBOX_CONNECTION
        and return_path == "/agent"
        else return_path
    )
    response = RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
    if result.purpose is AuthorizationPurpose.ADMIN_LOGIN:
        response.set_cookie(
            sessions.cookie_name,
            sessions.issue(
                result.connection_id,
                admin_home_account_id=result.home_account_id,
                admin_tenant_id=result.tenant_id,
            ),
            httponly=True,
            secure=_secure_cookie(request),
            samesite="lax",
            max_age=sessions.cookie_max_age,
            path="/",
        )
    response.delete_cookie(sessions.return_cookie_name, path="/auth")
    return response
