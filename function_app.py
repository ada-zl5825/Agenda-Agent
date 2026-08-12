"""Azure Functions ASGI adapter with no business logic."""

import azure.functions as func

from recruitment_agent.api.app import app as fastapi_app

app = func.AsgiFunctionApp(
    app=fastapi_app,
    http_auth_level=func.AuthLevel.ANONYMOUS,
)
