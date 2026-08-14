"""FastAPI composition root.

Routes intentionally delegate to application services. Phase 0 exposes only a
side-effect-free health endpoint.
"""

from typing import Literal

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from recruitment_agent import __version__
from recruitment_agent.api.agent import router as agent_router
from recruitment_agent.api.auth import router as auth_router
from recruitment_agent.api.briefs import router as briefs_router
from recruitment_agent.api.operations import router as operations_router
from recruitment_agent.api.reviews import router as reviews_router
from recruitment_agent.application.errors import ApplicationError


class HealthResponse(BaseModel):
    """Stable health-check contract."""

    status: Literal["ok"] = "ok"
    version: str


def create_app() -> FastAPI:
    """Build the HTTP application without loading external connections."""
    application = FastAPI(
        title="Recruitment Inbox Agent",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        # The control-plane path catalog must not be publicly enumerable.
        openapi_url=None,
    )
    application.include_router(agent_router)
    application.include_router(auth_router)
    application.include_router(briefs_router)
    application.include_router(operations_router)
    application.include_router(reviews_router)

    @application.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        return RedirectResponse(url="/agent", status_code=status.HTTP_303_SEE_OTHER)

    @application.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        status_by_code = {
            "AUTH_REQUIRED": status.HTTP_401_UNAUTHORIZED,
            "GRAPH_AUTH_ERROR": status.HTTP_401_UNAUTHORIZED,
            "REVIEW_ACCESS_DENIED": status.HTTP_403_FORBIDDEN,
            "REVIEW_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            "REVIEW_CONFLICT": status.HTTP_409_CONFLICT,
            "CSRF_INVALID": status.HTTP_403_FORBIDDEN,
            "OPS_AUTH_REQUIRED": status.HTTP_401_UNAUTHORIZED,
            "OPERATION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            "OPERATION_CONFLICT": status.HTTP_409_CONFLICT,
            "OPERATION_DISABLED": status.HTTP_423_LOCKED,
        }
        http_status = status_by_code.get(exc.code, status.HTTP_502_BAD_GATEWAY)
        headers = {"WWW-Authenticate": "Bearer"} if exc.code == "OPS_AUTH_REQUIRED" else None
        return JSONResponse(
            status_code=http_status,
            content={"error": exc.code},
            headers=headers,
        )

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    @application.get("/health/live", response_model=HealthResponse, tags=["operations"])
    async def health_live() -> HealthResponse:
        return HealthResponse(version=__version__)

    return application


app = create_app()
