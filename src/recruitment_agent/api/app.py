"""FastAPI composition root.

Routes intentionally delegate to application services. Phase 0 exposes only a
side-effect-free health endpoint.
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from recruitment_agent import __version__


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

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    return application


app = create_app()
