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
from recruitment_agent.api.briefs import router as briefs_router
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
    )
    application.include_router(auth_router)
    application.include_router(briefs_router)
    application.include_router(reviews_router)

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
        }
        http_status = status_by_code.get(exc.code, status.HTTP_502_BAD_GATEWAY)
        return JSONResponse(status_code=http_status, content={"error": exc.code})

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    return application


app = create_app()
