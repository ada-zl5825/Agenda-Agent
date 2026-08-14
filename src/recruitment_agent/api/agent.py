"""Authenticated HTML transport for the visual Phase 9A control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import parse_qs, quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from recruitment_agent.api.dependencies import get_web_session_manager
from recruitment_agent.application.agent_console import (
    AgentConsoleService,
    AgentControlCommand,
    AgentControlSwitch,
    AgentManualAction,
    AgentOperationCommand,
    DailyBriefRecipientCommand,
)
from recruitment_agent.application.errors import (
    OperationConflictError,
    OperationDisabledError,
    ReviewAuthenticationError,
)
from recruitment_agent.dashboard.renderer import AgentDashboardRenderer
from recruitment_agent.jobs.operations import operations_control_service
from recruitment_agent.web.security import WebSession, WebSessionManager

router = APIRouter(prefix="/agent", tags=["agent-console"])
SessionDependency = Annotated[WebSessionManager, Depends(get_web_session_manager)]
_renderer = AgentDashboardRenderer()


@dataclass(frozen=True, slots=True)
class AuthenticatedAgentSession:
    """Validated browser state required before opening external dependencies."""

    token: str
    session: WebSession
    manager: WebSessionManager


def get_authenticated_agent_session(
    request: Request,
    sessions: SessionDependency,
) -> AuthenticatedAgentSession:
    token = request.cookies.get(sessions.cookie_name)
    try:
        session = sessions.authenticate(token)
    except ReviewAuthenticationError as exc:
        redirect = _login_redirect()
        raise HTTPException(
            status_code=redirect.status_code,
            headers={"Location": redirect.headers["location"]},
        ) from exc
    assert token is not None
    return AuthenticatedAgentSession(
        token=token,
        session=session,
        manager=sessions,
    )


AgentSessionDependency = Annotated[
    AuthenticatedAgentSession,
    Depends(get_authenticated_agent_session),
]


async def get_agent_console_service(
    _authenticated: AgentSessionDependency,
) -> AsyncIterator[AgentConsoleService]:
    async with operations_control_service() as operations:
        yield AgentConsoleService(operations)


ConsoleDependency = Annotated[AgentConsoleService, Depends(get_agent_console_service)]


def _login_redirect() -> RedirectResponse:
    return RedirectResponse(
        url=f"/auth/login?return_to={quote('/agent', safe='/')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _redirect(*, notice: str | None = None, error: str | None = None) -> RedirectResponse:
    query = ""
    if notice is not None:
        query = f"?notice={quote(notice, safe='')}"
    elif error is not None:
        query = f"?error={quote(error, safe='')}"
    return RedirectResponse(url=f"/agent{query}", status_code=status.HTTP_303_SEE_OTHER)


async def _read_form(request: Request) -> dict[str, str]:
    raw = await request.body()
    if len(raw) > 16_384:
        raise ValueError("form is too large")
    values = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    return {key: items[0] for key, items in values.items() if items}


def _version(form: dict[str, str]) -> int:
    value = int(form.get("expected_version", "0"))
    if value < 1:
        raise ValueError("expected version must be positive")
    return value


@router.get("", response_class=HTMLResponse, response_model=None)
async def agent_console(
    authenticated: AgentSessionDependency,
    service: ConsoleDependency,
    operation_id: UUID | None = None,
    notice: str | None = None,
    error: str | None = None,
) -> HTMLResponse | RedirectResponse:
    snapshot = await service.get_snapshot(
        account_id=authenticated.session.connection_id,
        operation_id=operation_id,
    )
    version = snapshot.status.control.version
    csrf_tokens = {
        action: authenticated.manager.action_csrf_token(
            session_token=authenticated.token,
            action=action,
            version=version,
        )
        for action in (
            *(f"control:{switch.value}" for switch in AgentControlSwitch),
            *(f"operation:{operation.value}" for operation in AgentManualAction),
            "settings:daily_brief_recipient",
        )
    }
    operation_keys = {
        action.value: f"web-{action.value}-{uuid4()}" for action in AgentManualAction
    }
    return HTMLResponse(
        _renderer.render(
            snapshot,
            csrf_tokens=csrf_tokens,
            operation_keys=operation_keys,
            notice=notice,
            error=error,
        )
    )


@router.post("/control/{control_switch}", response_class=RedirectResponse)
async def update_agent_control(
    control_switch: AgentControlSwitch,
    request: Request,
    authenticated: AgentSessionDependency,
    service: ConsoleDependency,
) -> RedirectResponse:
    try:
        form = await _read_form(request)
        version = _version(form)
        enabled_text = form.get("enabled")
        if enabled_text not in {"true", "false"}:
            raise ValueError("enabled must be a boolean")
        authenticated.manager.verify_action_csrf(
            session_token=authenticated.token,
            action=f"control:{control_switch.value}",
            version=version,
            supplied=form.get("csrf_token", ""),
        )
        await service.update_control(
            account_id=authenticated.session.connection_id,
            command=AgentControlCommand(
                switch=control_switch,
                enabled=enabled_text == "true",
                expected_version=version,
            ),
        )
    except (TypeError, UnicodeDecodeError, ValueError):
        return _redirect(error="INVALID_REQUEST")
    except (OperationConflictError, OperationDisabledError) as exc:
        return _redirect(error=exc.code)
    return _redirect(notice="control-updated")


@router.post("/settings/daily-brief-recipient", response_class=RedirectResponse)
async def update_daily_brief_recipient(
    request: Request,
    authenticated: AgentSessionDependency,
    service: ConsoleDependency,
) -> RedirectResponse:
    try:
        form = await _read_form(request)
        version = _version(form)
        authenticated.manager.verify_action_csrf(
            session_token=authenticated.token,
            action="settings:daily_brief_recipient",
            version=version,
            supplied=form.get("csrf_token", ""),
        )
        await service.update_daily_brief_recipient(
            account_id=authenticated.session.connection_id,
            command=DailyBriefRecipientCommand(
                recipient=form.get("recipient", ""),
                expected_version=version,
            ),
        )
    except (TypeError, UnicodeDecodeError, ValueError):
        return _redirect(error="INVALID_RECIPIENT")
    except (OperationConflictError, OperationDisabledError) as exc:
        return _redirect(error=exc.code)
    return _redirect(notice="recipient-updated")


@router.post("/operations/{action}", response_class=RedirectResponse)
async def submit_agent_operation(
    action: AgentManualAction,
    request: Request,
    authenticated: AgentSessionDependency,
    service: ConsoleDependency,
) -> RedirectResponse:
    try:
        form = await _read_form(request)
        version = _version(form)
        authenticated.manager.verify_action_csrf(
            session_token=authenticated.token,
            action=f"operation:{action.value}",
            version=version,
            supplied=form.get("csrf_token", ""),
        )
        batch_limit = (
            int(form.get("batch_limit", "0"))
            if action is AgentManualAction.PROCESS_PENDING
            else None
        )
        operation = await service.submit_operation(
            account_id=authenticated.session.connection_id,
            command=AgentOperationCommand(
                action=action,
                expected_control_version=version,
                idempotency_key=form.get("idempotency_key", ""),
                batch_limit=batch_limit,
            ),
        )
    except (TypeError, UnicodeDecodeError, ValueError):
        return _redirect(error="INVALID_REQUEST")
    except (OperationConflictError, OperationDisabledError) as exc:
        return _redirect(error=exc.code)
    return RedirectResponse(
        url=f"/agent?operation_id={operation.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
