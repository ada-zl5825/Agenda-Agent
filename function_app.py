"""Azure Functions ASGI adapter with no business logic."""

import json
from uuid import UUID

import azure.functions as func

from recruitment_agent.api.app import app as fastapi_app
from recruitment_agent.jobs.operations import (
    run_operation_dispatch_job,
    run_operation_job,
    run_scheduled_daily_brief_job,
    run_scheduled_mail_sync_job,
)

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
    await run_scheduled_mail_sync_job()


@app.timer_trigger(
    arg_name="timer",
    schedule="%DAILY_BRIEF_SCHEDULE%",
    run_on_startup=False,
    use_monitor=True,
)
async def daily_brief_timer(timer: func.TimerRequest) -> None:
    """Invoke the idempotent Phase 8 service; no rendering logic lives here."""
    del timer
    await run_scheduled_daily_brief_job()


@app.queue_trigger(
    arg_name="message",
    queue_name="%OPS_QUEUE_NAME%",
    connection="AzureWebJobsStorage",
)
async def operations_queue_worker(message: func.QueueMessage) -> None:
    """Invoke one audited command using only its opaque operation identifier."""
    payload = json.loads(message.get_body().decode("utf-8"))
    operation_id = UUID(str(payload["operation_id"]))
    delivery_attempt = int(getattr(message, "dequeue_count", 1) or 1)
    await run_operation_job(operation_id, delivery_attempt=delivery_attempt)


@app.timer_trigger(
    arg_name="timer",
    schedule="%OPS_DISPATCH_SCHEDULE%",
    run_on_startup=False,
    use_monitor=True,
)
async def operations_dispatch_timer(timer: func.TimerRequest) -> None:
    """Recover queued audit rows after a transient dispatch failure."""
    del timer
    await run_operation_dispatch_job()
