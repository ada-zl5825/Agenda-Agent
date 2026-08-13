"""Azure Functions ASGI adapter with no business logic."""

import azure.functions as func

from recruitment_agent.api.app import app as fastapi_app
from recruitment_agent.jobs.daily_brief import run_daily_brief_job
from recruitment_agent.jobs.mail_sync import run_mail_sync_job

app = func.AsgiFunctionApp(
    app=fastapi_app,
    http_auth_level=func.AuthLevel.ANONYMOUS,
)


@app.timer_trigger(
    arg_name="timer",
    schedule="%MAIL_SYNC_SCHEDULE%",
    run_on_startup=False,
    use_monitor=True,
)
async def mail_sync_timer(timer: func.TimerRequest) -> None:
    """Invoke the Phase 1 application job; the trigger contains no business rules."""
    del timer
    await run_mail_sync_job()


@app.timer_trigger(
    arg_name="timer",
    schedule="%DAILY_BRIEF_SCHEDULE%",
    run_on_startup=False,
    use_monitor=True,
)
async def daily_brief_timer(timer: func.TimerRequest) -> None:
    """Invoke the idempotent Phase 8 service; no rendering logic lives here."""
    del timer
    await run_daily_brief_job()
