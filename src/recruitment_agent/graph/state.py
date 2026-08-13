"""Checkpoint-safe execution state for the Recruitment Mail StateGraph."""

from typing import NotRequired, TypedDict


class RecruitmentGraphInput(TypedDict):
    processing_run_id: str
    graph_thread_id: str
    source_email_id: str
    prompt_version: str
    model_deployment: str | None
    current_stage: str
    status: str


class RecruitmentGraphState(RecruitmentGraphInput):
    """Execution references and sanitized structured evidence only."""

    account_id: NotRequired[str]
    graph_message_id: NotRequired[str]
    sender_domain: NotRequired[str | None]
    received_at: NotRequired[str]
    sanitized_text: NotRequired[str]
    link_refs: NotRequired[list[str]]
    prefilter_decision: NotRequired[str]
    extraction_result: NotRequired[dict[str, object]]
    validation_errors: NotRequired[list[str]]
    review_request: NotRequired[dict[str, object]]
    review_id: NotRequired[str]
    review_resolution: NotRequired[dict[str, object]]
    reviewed_reasons: NotRequired[list[str]]
    review_resume_stage: NotRequired[str]
    reviewed_company_id: NotRequired[str | None]
    reviewed_timezone: NotRequired[str | None]
    force_create_application: NotRequired[bool]
    selected_application_id: NotRequired[str | None]
    selected_event_id: NotRequired[str | None]
    treat_reschedule_as_new: NotRequired[bool]
    application_resolution: NotRequired[dict[str, object]]
    event_resolution: NotRequired[dict[str, object]]
    transition_plan: NotRequired[dict[str, object]]
    application_id: NotRequired[str | None]
    event_id: NotRequired[str | None]
    action_item_ids: NotRequired[list[str]]
    calendar_operation: NotRequired[dict[str, object]]
    replace_missing_calendar_event: NotRequired[bool]
    skip_calendar_update: NotRequired[bool]
    error_code: NotRequired[str | None]
