"""Authenticated HTML transport for human Review."""

from typing import Annotated
from urllib.parse import parse_qs, quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from recruitment_agent.api.dependencies import get_review_service, get_web_session_manager
from recruitment_agent.application.errors import ApplicationError, ReviewAuthenticationError
from recruitment_agent.application.reviews import ReviewService
from recruitment_agent.reviews.renderer import ReviewHtmlRenderer
from recruitment_agent.web.security import WebSessionManager

router = APIRouter(prefix="/reviews", tags=["reviews"])
ReviewServiceDependency = Annotated[ReviewService, Depends(get_review_service)]
SessionDependency = Annotated[WebSessionManager, Depends(get_web_session_manager)]
_renderer = ReviewHtmlRenderer()


def _login_redirect(path: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"/auth/login?return_to={quote(path, safe='/')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("", response_class=HTMLResponse, response_model=None)
async def list_reviews(
    request: Request,
    service: ReviewServiceDependency,
    sessions: SessionDependency,
) -> HTMLResponse | RedirectResponse:
    token = request.cookies.get(sessions.cookie_name)
    try:
        session = sessions.authenticate(token)
    except ReviewAuthenticationError:
        return _login_redirect("/reviews")
    items = await service.list_open(account_id=session.connection_id)
    return HTMLResponse(_renderer.queue(items))


@router.get("/{review_id}", response_class=HTMLResponse, response_model=None)
async def review_detail(
    review_id: UUID,
    request: Request,
    service: ReviewServiceDependency,
    sessions: SessionDependency,
) -> HTMLResponse | RedirectResponse:
    token = request.cookies.get(sessions.cookie_name)
    try:
        session = sessions.authenticate(token)
    except ReviewAuthenticationError:
        return _login_redirect(f"/reviews/{review_id}")
    detail = await service.get_detail(account_id=session.connection_id, review_id=review_id)
    assert token is not None
    csrf = sessions.csrf_token(
        session_token=token,
        review_id=review_id,
        version=detail.version,
    )
    return HTMLResponse(
        _renderer.detail(
            detail,
            csrf_token=csrf,
            error=request.query_params.get("error"),
        )
    )


@router.post("/{review_id}/resolve", response_class=RedirectResponse)
async def resolve_review(
    review_id: UUID,
    request: Request,
    service: ReviewServiceDependency,
    sessions: SessionDependency,
) -> RedirectResponse:
    token = request.cookies.get(sessions.cookie_name)
    try:
        session = sessions.authenticate(token)
    except ReviewAuthenticationError:
        return _login_redirect(f"/reviews/{review_id}")
    raw_body = await request.body()
    if len(raw_body) > 16_384:
        return RedirectResponse(f"/reviews/{review_id}", status_code=303)
    try:
        decoded_body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return RedirectResponse(f"/reviews/{review_id}", status_code=303)
    form = parse_qs(decoded_body, keep_blank_values=True)
    choice = form.get("choice", [""])[0]
    override = form.get("override_value", [""])[0].strip() or None
    clock_override = form.get("clock_override", [""])[0].strip() or None
    csrf = form.get("csrf_token", [""])[0]
    try:
        version = int(form.get("expected_version", ["0"])[0])
    except ValueError:
        version = 0
    assert token is not None
    sessions.verify_csrf(
        session_token=token,
        review_id=review_id,
        version=version,
        supplied=csrf,
    )
    try:
        resolved = await service.resolve(
            account_id=session.connection_id,
            review_id=review_id,
            choice=choice,
            override_value=override,
            expected_version=version,
            clock_override=clock_override,
        )
    except ApplicationError as exc:
        return RedirectResponse(
            url=f"/reviews/{review_id}?error={quote(exc.code, safe='')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    nxt = await service.next_open_for_source(
        account_id=session.connection_id,
        source_email_id=resolved.source_email_id,
        excluding_review_id=review_id,
    )
    destination = f"/reviews/{nxt}" if nxt is not None else "/reviews"
    return RedirectResponse(
        url=destination,
        status_code=status.HTTP_303_SEE_OTHER,
    )
