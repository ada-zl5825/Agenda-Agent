"""FastAPI composition root.

Routes intentionally delegate to application services. Phase 0 exposes only a
side-effect-free health endpoint.
"""

from typing import Literal

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from recruitment_agent import __version__
from recruitment_agent.api.auth import router as auth_router
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
    )
    application.include_router(auth_router)

    @application.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        http_status = (
            status.HTTP_401_UNAUTHORIZED
            if exc.code in {"AUTH_REQUIRED", "GRAPH_AUTH_ERROR"}
            else status.HTTP_502_BAD_GATEWAY
        )
        return JSONResponse(status_code=http_status, content={"error": exc.code})

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    return application


app = create_app()
