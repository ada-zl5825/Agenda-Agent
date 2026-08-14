"""Authenticated Daily Brief preview route."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from recruitment_agent.api.dependencies import get_web_session_manager
from recruitment_agent.application.errors import ReviewAuthenticationError
from recruitment_agent.jobs.daily_brief import preview_daily_brief_today
from recruitment_agent.web.security import WebSessionManager

router = APIRouter(prefix="/brief", tags=["daily-brief"])
SessionDependency = Annotated[WebSessionManager, Depends(get_web_session_manager)]
BriefPreview = Callable[..., Awaitable[str]]


def get_brief_renderer() -> BriefPreview:
    return preview_daily_brief_today


@router.get("/today", response_class=HTMLResponse, response_model=None)
async def brief_today(
    request: Request,
    sessions: SessionDependency,
    render: Annotated[BriefPreview, Depends(get_brief_renderer)],
) -> HTMLResponse | RedirectResponse:
    try:
        session = sessions.authenticate(request.cookies.get(sessions.cookie_name))
    except ReviewAuthenticationError:
        return RedirectResponse(
            url="/auth/login?return_to=/brief/today",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return HTMLResponse(await render(account_id=session.connection_id))
