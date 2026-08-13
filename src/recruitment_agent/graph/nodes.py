"""Small explicit nodes for the Phase 5 Recruitment Mail StateGraph."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from recruitment_agent.extraction.models import (
    ExtractionIssueCode,
    ExtractionValidationStatus,
)
from recruitment_agent.graph.context import RecruitmentGraphContext
from recruitment_agent.graph.contracts import (
    ExtractionAudit,
    ProcessingRun,
    ProcessingRunStatus,
    ReviewItem,
    ReviewRequest,
    ReviewType,
    SafePreparedEmail,
    WorkflowExtractionResult,
    WorkflowPrefilterDecision,
    WorkflowStage,
    validate_review_decision,
)
from recruitment_agent.graph.state import RecruitmentGraphState

_PLAINTEXT_URL = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]*://|\bmailto:|\bwww\.)")
_LINK_REF = re.compile(r"^ACTION_LINK_[0-9]{2,}$")


def _run_id(state: RecruitmentGraphState) -> UUID:
    return UUID(state["processing_run_id"])


def _source_email_id(state: RecruitmentGraphState) -> UUID:
    return UUID(state["source_email_id"])


async def _advance(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
    stage: WorkflowStage,
    *,
    status: ProcessingRunStatus = ProcessingRunStatus.RUNNING,
) -> None:
    await runtime.context.persistence.advance_run(
        processing_run_id=_run_id(state),
        stage=stage,
        status=status,
    )


async def load_source_email(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.LOAD_SOURCE_EMAIL
    run = ProcessingRun(
        id=_run_id(state),
        source_email_id=_source_email_id(state),
        graph_thread_id=state["graph_thread_id"],
        current_stage=stage,
        status=ProcessingRunStatus.RUNNING,
        prompt_version=state["prompt_version"],
        model_deployment=state["model_deployment"],
        started_at=runtime.context.clock.now(),
    )
    source_email = await runtime.context.persistence.load_source_email(
        _source_email_id(state)
    )
    if source_email.id != _source_email_id(state):
        raise ValueError("loaded source email identity does not match the workflow")
    await runtime.context.persistence.start_run(run)
    return {
        "current_stage": stage.value,
        "status": ProcessingRunStatus.RUNNING.value,
        "account_id": str(source_email.account_id),
        "graph_message_id": source_email.graph_message_id,
    }


async def normalize_email(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    """Run the transient preparation pipeline and retain only checkpoint-safe output."""
    stage = WorkflowStage.NORMALIZE_EMAIL
    await _advance(state, runtime, stage)
    prepared = await runtime.context.activities.prepare_email(
        account_id=UUID(state["account_id"]),
        source_email_id=_source_email_id(state),
        graph_message_id=state["graph_message_id"],
    )
    if prepared.source_email_id != _source_email_id(state):
        raise ValueError("prepared email identity does not match the workflow")
    return {
        "current_stage": stage.value,
        "sender_domain": prepared.sender_domain,
        "received_at": prepared.received_at.isoformat(),
        "sanitized_text": prepared.sanitized_text,
        "link_refs": list(prepared.link_refs),
        "prefilter_decision": prepared.prefilter_decision.value,
    }


async def extract_action_links(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.EXTRACT_ACTION_LINKS
    await _advance(state, runtime, stage)
    refs = state.get("link_refs", [])
    if len(refs) != len(set(refs)) or any(_LINK_REF.fullmatch(ref) is None for ref in refs):
        raise ValueError("checkpoint-safe link references are invalid")
    return {"current_stage": stage.value}


async def prefilter_recruitment(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.PREFILTER_RECRUITMENT
    await _advance(state, runtime, stage)
    WorkflowPrefilterDecision(state["prefilter_decision"])
    return {"current_stage": stage.value}


def route_after_prefilter(
    state: RecruitmentGraphState,
) -> Literal["sanitize_content", "mark_ignored"]:
    if (
        WorkflowPrefilterDecision(state["prefilter_decision"])
        is WorkflowPrefilterDecision.UNLIKELY
    ):
        return "mark_ignored"
    return "sanitize_content"


async def sanitize_content(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.SANITIZE_CONTENT
    await _advance(state, runtime, stage)
    sanitized_text = state.get("sanitized_text", "")
    if not sanitized_text.strip():
        raise ValueError("sanitized evidence must not be empty")
    if _PLAINTEXT_URL.search(sanitized_text):
        raise ValueError("sanitized evidence contains forbidden URL material")
    return {"current_stage": stage.value}


def _safe_prepared(state: RecruitmentGraphState) -> SafePreparedEmail:
    return SafePreparedEmail(
        source_email_id=_source_email_id(state),
        sender_domain=state.get("sender_domain"),
        received_at=datetime.fromisoformat(state["received_at"]),
        sanitized_text=state["sanitized_text"],
        link_refs=tuple(state.get("link_refs", [])),
        prefilter_decision=WorkflowPrefilterDecision(state["prefilter_decision"]),
    )


async def extract_recruitment_data(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.EXTRACT_RECRUITMENT_DATA
    await _advance(state, runtime, stage)
    result = await runtime.context.activities.extract_recruitment_data(
        _safe_prepared(state)
    )
    audit = ExtractionAudit.create(
        processing_run_id=_run_id(state),
        source_email_id=_source_email_id(state),
        result=result,
        created_at=runtime.context.clock.now(),
    )
    persisted_result = await runtime.context.persistence.record_extraction(audit)
    return {
        "current_stage": stage.value,
        "extraction_result": persisted_result.model_dump(mode="json"),
    }


def _timezone_review(reason: str) -> ReviewRequest:
    return ReviewRequest(
        review_type=ReviewType.TIMEZONE_AMBIGUITY,
        reason=reason,
        question="Select the timezone supported by the source evidence.",
        allowed_choices=("Europe/London", "Asia/Shanghai", "other", "ignore"),
    )


def _datetime_review(reason: str) -> ReviewRequest:
    return ReviewRequest(
        review_type=ReviewType.DATETIME_CONFLICT,
        reason=reason,
        question="Choose how to handle the conflicting date or time evidence.",
        allowed_choices=("use_extracted", "ignore"),
    )


def _application_review(
    reason: str,
    result: WorkflowExtractionResult,
) -> ReviewRequest:
    company = result.company
    candidate_ids = () if company is None else company.candidate_company_ids
    return ReviewRequest(
        review_type=ReviewType.APPLICATION_AMBIGUITY,
        reason=reason,
        question="Select the reviewed identity or ignore this workflow.",
        allowed_choices=(*tuple(str(value) for value in candidate_ids), "ignore"),
    )


def _next_review_request(
    result: WorkflowExtractionResult,
    reviewed_reasons: set[str],
) -> ReviewRequest | None:
    issue_codes = {issue.code for issue in result.validation.issues}
    if ExtractionIssueCode.TIMEZONE_CONFLICT in issue_codes:
        reason = "datetime_conflict"
        if reason not in reviewed_reasons:
            return _datetime_review(reason)
    timezone_codes = {
        ExtractionIssueCode.TIMEZONE_AMBIGUOUS,
        ExtractionIssueCode.DATETIME_UNRESOLVED,
        ExtractionIssueCode.DEADLINE_UNRESOLVED,
    }
    if issue_codes & timezone_codes:
        reason = "timezone_ambiguity"
        if reason not in reviewed_reasons:
            return _timezone_review(reason)
    recognized_codes = timezone_codes | {ExtractionIssueCode.TIMEZONE_CONFLICT}
    if (
        result.validation.status is ExtractionValidationStatus.NEEDS_REVIEW
        and issue_codes - recognized_codes
    ):
        reason = "extraction_needs_review"
        if reason not in reviewed_reasons:
            return _application_review(reason, result)
    company = result.company
    if company is not None and company.company_id is None:
        reason = f"company_{company.status}"
        if reason not in reviewed_reasons:
            return _application_review(reason, result)
    return None


async def validate_extraction(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.VALIDATE_EXTRACTION
    await _advance(state, runtime, stage)
    result = WorkflowExtractionResult.model_validate(state["extraction_result"])
    errors = [issue.code.value for issue in result.validation.issues]
    if result.validation.status is ExtractionValidationStatus.INVALID:
        return {
            "current_stage": stage.value,
            "status": ProcessingRunStatus.FAILED.value,
            "validation_errors": errors,
            "error_code": "LLM_SCHEMA_INVALID",
        }
    if not result.extraction.relevant:
        return {
            "current_stage": stage.value,
            "status": ProcessingRunStatus.IGNORED.value,
            "validation_errors": errors,
        }
    review = _next_review_request(result, set(state.get("reviewed_reasons", [])))
    if review is not None:
        return {
            "current_stage": stage.value,
            "status": ProcessingRunStatus.NEEDS_REVIEW.value,
            "validation_errors": errors,
            "review_request": review.model_dump(mode="json"),
        }
    return {
        "current_stage": stage.value,
        "status": ProcessingRunStatus.RUNNING.value,
        "validation_errors": errors,
    }


def route_after_validation(
    state: RecruitmentGraphState,
) -> Literal["request_review", "resolve_application", "mark_ignored", "finalize_processing"]:
    status = ProcessingRunStatus(state["status"])
    if status is ProcessingRunStatus.NEEDS_REVIEW:
        return "request_review"
    if status is ProcessingRunStatus.IGNORED:
        return "mark_ignored"
    if status is ProcessingRunStatus.FAILED:
        return "finalize_processing"
    return "resolve_application"


async def request_review(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> Command[Literal["validate_extraction", "mark_ignored"]]:
    stage = WorkflowStage.REQUEST_REVIEW
    request = ReviewRequest.model_validate(state["review_request"])
    item = ReviewItem.create(
        processing_run_id=_run_id(state),
        request=request,
        created_at=runtime.context.clock.now(),
    )
    await runtime.context.persistence.open_review(item)
    await _advance(
        state,
        runtime,
        stage,
        status=ProcessingRunStatus.NEEDS_REVIEW,
    )
    payload: dict[str, object] = {
        "review_id": str(item.id),
        "review_type": request.review_type.value,
        "reason": request.reason,
        "question": request.question,
        "allowed_choices": list(request.allowed_choices),
        "version": item.version,
    }
    while True:
        raw_decision: object = interrupt(payload)
        try:
            decision = validate_review_decision(request, raw_decision)
        except ValueError:
            payload = {**payload, "validation_error": "invalid_review_decision"}
            continue
        break
    await runtime.context.persistence.resolve_review(
        review_id=item.id,
        decision=decision,
        resolved_at=runtime.context.clock.now(),
    )
    reviewed_reasons = [*state.get("reviewed_reasons", []), request.reason]
    update: dict[str, object] = {
        "current_stage": stage.value,
        "status": ProcessingRunStatus.RUNNING.value,
        "review_id": str(item.id),
        "review_resolution": decision.model_dump(mode="json"),
        "reviewed_reasons": reviewed_reasons,
    }
    if decision.choice == "ignore":
        return Command(goto="mark_ignored", update=update)
    if request.review_type is ReviewType.APPLICATION_AMBIGUITY:
        update["application_id"] = decision.choice
    return Command(goto="validate_extraction", update=update)


async def resolve_application(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.RESOLVE_APPLICATION
    await _advance(state, runtime, stage)
    return {"current_stage": stage.value, "application_id": state.get("application_id")}


async def resolve_existing_event(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.RESOLVE_EXISTING_EVENT
    await _advance(state, runtime, stage)
    return {"current_stage": stage.value, "event_id": None}


async def plan_state_transition(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.PLAN_STATE_TRANSITION
    await _advance(state, runtime, stage)
    return {"current_stage": stage.value, "action_item_ids": []}


async def persist_domain_changes(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    """Phase 6 placeholder: deliberately performs no domain mutation."""
    stage = WorkflowStage.PERSIST_DOMAIN_CHANGES
    await _advance(state, runtime, stage)
    return {"current_stage": stage.value}


async def sync_calendar_placeholder(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.SYNC_CALENDAR_PLACEHOLDER
    await _advance(state, runtime, stage)
    result = await runtime.context.calendar.sync(processing_run_id=_run_id(state))
    return {
        "current_stage": stage.value,
        "calendar_operation": result.model_dump(mode="json"),
    }


async def finalize_processing(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.FINALIZE_PROCESSING
    current_status = ProcessingRunStatus(state["status"])
    status = (
        ProcessingRunStatus.FAILED
        if current_status is ProcessingRunStatus.FAILED
        else ProcessingRunStatus.COMPLETED
    )
    await runtime.context.persistence.finalize_run(
        processing_run_id=_run_id(state),
        source_email_id=_source_email_id(state),
        stage=stage,
        status=status,
        finished_at=runtime.context.clock.now(),
        error_code=state.get("error_code"),
    )
    return {"current_stage": stage.value, "status": status.value}


async def mark_ignored(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.MARK_IGNORED
    await runtime.context.persistence.finalize_run(
        processing_run_id=_run_id(state),
        source_email_id=_source_email_id(state),
        stage=stage,
        status=ProcessingRunStatus.IGNORED,
        finished_at=runtime.context.clock.now(),
    )
    return {"current_stage": stage.value, "status": ProcessingRunStatus.IGNORED.value}
