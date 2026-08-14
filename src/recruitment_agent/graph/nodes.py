"""Small explicit nodes for the Phase 5/6 Recruitment Mail StateGraph."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from recruitment_agent.application.errors import TimeEvidenceUnresolvedError
from recruitment_agent.calendar.models import CalendarSyncRequest
from recruitment_agent.domain.processing import (
    ApplicationResolution,
    ApplicationResolutionKind,
    DomainTransitionPlan,
    EventResolution,
    EventResolutionKind,
    RecruitmentEvidence,
)
from recruitment_agent.extraction.models import (
    ExtractionIssueCode,
    ExtractionValidationStatus,
)
from recruitment_agent.graph.context import RecruitmentGraphContext
from recruitment_agent.graph.contracts import (
    COMBINED_DATETIME_REASON,
    COMBINED_DEADLINE_REASON,
    COMBINED_TIME_REASONS,
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
    parse_review_datetime,
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
        question="请为抽出的本地开始时间选择时区. 日期和钟点不变, 只绑定时区.",
        allowed_choices=("Europe/London", "Asia/Shanghai", "other", "ignore"),
    )


def _datetime_review(reason: str) -> ReviewRequest:
    return ReviewRequest(
        review_type=ReviewType.DATETIME_CONFLICT,
        reason=reason,
        question="Choose how to handle the conflicting date or time evidence.",
        allowed_choices=("use_extracted", "ignore"),
    )


def _unresolved_datetime_review(reason: str) -> ReviewRequest:
    if reason == "deadline_unresolved":
        question = (
            "邮件写了截止日期, 但无法解析成具体时钟. "
            "请填写截止日期 (到期时间, 不是面试结束时间), 格式 YYYY-MM-DD HH:MM, 或忽略."
        )
    else:
        question = (
            "邮件写了面试或事件的开始时间, 但无法解析成具体时钟. "
            "请填写开始时间 (不是结束时间), 格式 YYYY-MM-DD HH:MM, 或忽略."
        )
    return ReviewRequest(
        review_type=ReviewType.DATETIME_CONFLICT,
        reason=reason,
        question=question,
        allowed_choices=("use_override", "ignore"),
    )


def _combined_time_review(*, clock: str) -> ReviewRequest:
    if clock == "deadline":
        return ReviewRequest(
            review_type=ReviewType.TIMEZONE_AMBIGUITY,
            reason=COMBINED_DEADLINE_REASON,
            question=(
                "请选择时区, 并填写截止日期 (到期时间, 不是面试结束时间). "
                "日期格式 YYYY-MM-DD HH:MM."
            ),
            allowed_choices=("Europe/London", "Asia/Shanghai", "other", "ignore"),
        )
    return ReviewRequest(
        review_type=ReviewType.TIMEZONE_AMBIGUITY,
        reason=COMBINED_DATETIME_REASON,
        question=(
            "请选择时区, 并填写面试或事件的开始时间 (不是结束时间). "
            "日期格式 YYYY-MM-DD HH:MM."
        ),
        allowed_choices=("Europe/London", "Asia/Shanghai", "other", "ignore"),
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
        question=(
            "Select the reviewed company identity, create an unresolved application, "
            "or ignore."
        ),
        allowed_choices=(
            *tuple(str(value) for value in candidate_ids),
            "create_new",
            "ignore",
        ),
    )


def _application_resolution_review(
    resolution: ApplicationResolution,
) -> ReviewRequest:
    return ReviewRequest(
        review_type=ReviewType.APPLICATION_AMBIGUITY,
        reason=resolution.reason,
        question="Select the matching application, create a new application, or ignore.",
        allowed_choices=(
            *tuple(str(value) for value in resolution.candidate_application_ids),
            "create_new",
            "ignore",
        ),
    )


def _extraction_review(reason: str) -> ReviewRequest:
    return ReviewRequest(
        review_type=ReviewType.APPLICATION_AMBIGUITY,
        reason=reason,
        question="Accept the reviewed structured evidence or ignore this workflow.",
        allowed_choices=("accept", "ignore"),
    )


def _event_resolution_review(resolution: EventResolution) -> ReviewRequest:
    return ReviewRequest(
        review_type=ReviewType.UNCERTAIN_RESCHEDULE,
        reason=resolution.reason,
        question="Select the interview to reschedule, treat this as new, or ignore.",
        allowed_choices=(
            *tuple(str(value) for value in resolution.candidate_event_ids),
            "treat_as_new",
            "ignore",
        ),
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
    timezone_reviewed = bool(
        reviewed_reasons
        & {"timezone_ambiguity", COMBINED_DATETIME_REASON, COMBINED_DEADLINE_REASON}
    )
    datetime_reviewed = bool(
        reviewed_reasons & {"datetime_unresolved", COMBINED_DATETIME_REASON}
    )
    deadline_reviewed = bool(
        reviewed_reasons & {"deadline_unresolved", COMBINED_DEADLINE_REASON}
    )
    if ExtractionIssueCode.TIMEZONE_AMBIGUOUS in issue_codes and not timezone_reviewed:
        if ExtractionIssueCode.DATETIME_UNRESOLVED in issue_codes and not datetime_reviewed:
            return _combined_time_review(clock="datetime")
        if ExtractionIssueCode.DEADLINE_UNRESOLVED in issue_codes and not deadline_reviewed:
            return _combined_time_review(clock="deadline")
        return _timezone_review("timezone_ambiguity")
    if ExtractionIssueCode.DATETIME_UNRESOLVED in issue_codes and not datetime_reviewed:
        return _unresolved_datetime_review("datetime_unresolved")
    if ExtractionIssueCode.DEADLINE_UNRESOLVED in issue_codes and not deadline_reviewed:
        return _unresolved_datetime_review("deadline_unresolved")
    recognized_codes = {
        ExtractionIssueCode.TIMEZONE_CONFLICT,
        ExtractionIssueCode.TIMEZONE_AMBIGUOUS,
        ExtractionIssueCode.DATETIME_UNRESOLVED,
        ExtractionIssueCode.DEADLINE_UNRESOLVED,
    }
    if (
        result.validation.status is ExtractionValidationStatus.NEEDS_REVIEW
        and issue_codes - recognized_codes
    ):
        reason = "extraction_needs_review"
        if reason not in reviewed_reasons:
            return _extraction_review(reason)
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
            "review_resume_stage": stage.value,
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
) -> Command[
    Literal[
        "validate_extraction",
        "resolve_application",
        "resolve_existing_event",
        "sync_calendar_placeholder",
        "mark_ignored",
    ]
]:
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
    if request.reason == COMBINED_DATETIME_REASON:
        reviewed_reasons.extend(["timezone_ambiguity", "datetime_unresolved"])
    elif request.reason == COMBINED_DEADLINE_REASON:
        reviewed_reasons.extend(["timezone_ambiguity", "deadline_unresolved"])
    update: dict[str, object] = {
        "current_stage": stage.value,
        "status": ProcessingRunStatus.RUNNING.value,
        "review_id": str(item.id),
        "review_resolution": decision.model_dump(mode="json"),
        "reviewed_reasons": reviewed_reasons,
    }
    if decision.choice == "ignore":
        return Command(goto="mark_ignored", update=update)
    resume_stage = WorkflowStage(
        state.get("review_resume_stage", WorkflowStage.VALIDATE_EXTRACTION.value)
    )
    if request.review_type is ReviewType.TIMEZONE_AMBIGUITY:
        update["reviewed_timezone"] = (
            decision.override_value if decision.choice == "other" else decision.choice
        )
        if (
            request.reason in COMBINED_TIME_REASONS
            and decision.clock_override is not None
        ):
            parsed = parse_review_datetime(decision.clock_override).isoformat()
            if request.reason == COMBINED_DEADLINE_REASON:
                update["reviewed_deadline"] = parsed
            else:
                update["reviewed_event_datetime"] = parsed
    elif request.review_type is ReviewType.DATETIME_CONFLICT:
        if decision.choice == "use_override" and decision.override_value is not None:
            parsed = parse_review_datetime(decision.override_value).isoformat()
            if request.reason == "deadline_unresolved":
                update["reviewed_deadline"] = parsed
            else:
                update["reviewed_event_datetime"] = parsed
    elif request.review_type is ReviewType.APPLICATION_AMBIGUITY:
        if request.reason == "extraction_needs_review":
            pass
        elif resume_stage is WorkflowStage.VALIDATE_EXTRACTION:
            if decision.choice == "create_new":
                update["force_create_application"] = True
            else:
                update["reviewed_company_id"] = decision.choice
        elif decision.choice == "create_new":
            update["force_create_application"] = True
        else:
            update["selected_application_id"] = decision.choice
    elif request.review_type is ReviewType.UNCERTAIN_RESCHEDULE:
        if decision.choice == "treat_as_new":
            update["treat_reschedule_as_new"] = True
        else:
            update["selected_event_id"] = decision.choice
    elif request.review_type is ReviewType.UNSAFE_CALENDAR_UPDATE:
        if decision.choice == "apply_proposed_update":
            update["replace_missing_calendar_event"] = True
        elif decision.choice == "skip_calendar_update":
            update["skip_calendar_update"] = True

    destination: Literal[
        "validate_extraction",
        "resolve_application",
        "resolve_existing_event",
        "sync_calendar_placeholder",
    ]
    if resume_stage is WorkflowStage.VALIDATE_EXTRACTION:
        destination = "validate_extraction"
    elif resume_stage is WorkflowStage.RESOLVE_APPLICATION:
        destination = "resolve_application"
    elif resume_stage is WorkflowStage.RESOLVE_EXISTING_EVENT:
        destination = "resolve_existing_event"
    elif resume_stage is WorkflowStage.SYNC_CALENDAR:
        destination = "sync_calendar_placeholder"
    else:
        raise ValueError("review resume stage is not supported")
    return Command(goto=destination, update=update)


def _domain_evidence(state: RecruitmentGraphState) -> RecruitmentEvidence:
    result = WorkflowExtractionResult.model_validate(state["extraction_result"])
    extraction = result.extraction
    reviewed_company_id = state.get("reviewed_company_id")
    company_id = (
        UUID(reviewed_company_id)
        if reviewed_company_id is not None
        else None if result.company is None else result.company.company_id
    )
    timezone = state.get("reviewed_timezone")
    event_datetime = extraction.event_datetime
    deadline = extraction.deadline
    reviewed_event_datetime = state.get("reviewed_event_datetime")
    reviewed_deadline = state.get("reviewed_deadline")
    if reviewed_event_datetime is not None:
        event_datetime = datetime.fromisoformat(reviewed_event_datetime)
    if reviewed_deadline is not None:
        deadline = datetime.fromisoformat(reviewed_deadline)
    if timezone is not None:
        # A human resolved the ambiguous timezone. The extracted values carry
        # the email's wall-clock time with an unknown or invented offset, so
        # rebind that wall-clock reading to the reviewed IANA zone; otherwise
        # the label changes while the absolute instant stays wrong.
        zone = ZoneInfo(timezone)
        if event_datetime is not None:
            event_datetime = event_datetime.replace(tzinfo=zone)
        if deadline is not None:
            deadline = deadline.replace(tzinfo=zone)
    elif extraction.timezone_explicit:
        timezone = extraction.timezone_text
    return RecruitmentEvidence(
        source_email_id=_source_email_id(state),
        company_id=company_id,
        raw_company_name=extraction.company_raw,
        role_name=extraction.role_raw,
        role_normalized=None if result.role is None else result.role.normalized_name,
        event_type=extraction.event_type,
        interview_round=extraction.interview_round,
        action_required=extraction.action_required,
        action_text=extraction.action_text,
        action_link_ref=extraction.action_link_ref,
        event_datetime=event_datetime,
        deadline=deadline,
        timezone=timezone,
        source_datetime_text=extraction.source_datetime_text,
        source_deadline_text=extraction.source_deadline_text,
    )


async def resolve_application(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.RESOLVE_APPLICATION
    await _advance(state, runtime, stage)
    selected = state.get("selected_application_id")
    resolution = await runtime.context.domain.resolve_application(
        _domain_evidence(state),
        selected_application_id=None if selected is None else UUID(selected),
        force_create=state.get("force_create_application", False),
    )
    update: dict[str, object] = {
        "current_stage": stage.value,
        "application_resolution": resolution.model_dump(mode="json"),
        "application_id": (
            None if resolution.application_id is None else str(resolution.application_id)
        ),
    }
    if resolution.kind is ApplicationResolutionKind.REVIEW:
        update.update(
            {
                "status": ProcessingRunStatus.NEEDS_REVIEW.value,
                "review_request": _application_resolution_review(resolution).model_dump(
                    mode="json"
                ),
                "review_resume_stage": stage.value,
            }
        )
    else:
        update["status"] = ProcessingRunStatus.RUNNING.value
    return update


def route_after_application_resolution(
    state: RecruitmentGraphState,
) -> Literal["request_review", "resolve_existing_event"]:
    if ProcessingRunStatus(state["status"]) is ProcessingRunStatus.NEEDS_REVIEW:
        return "request_review"
    return "resolve_existing_event"


async def resolve_existing_event(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.RESOLVE_EXISTING_EVENT
    await _advance(state, runtime, stage)
    application = ApplicationResolution.model_validate(state["application_resolution"])
    selected = state.get("selected_event_id")
    resolution = await runtime.context.domain.resolve_event(
        _domain_evidence(state),
        application,
        selected_event_id=None if selected is None else UUID(selected),
        treat_as_new=state.get("treat_reschedule_as_new", False),
    )
    update: dict[str, object] = {
        "current_stage": stage.value,
        "event_resolution": resolution.model_dump(mode="json"),
        "event_id": None if resolution.event_id is None else str(resolution.event_id),
    }
    if resolution.kind is EventResolutionKind.REVIEW:
        update.update(
            {
                "status": ProcessingRunStatus.NEEDS_REVIEW.value,
                "review_request": _event_resolution_review(resolution).model_dump(mode="json"),
                "review_resume_stage": stage.value,
            }
        )
    else:
        update["status"] = ProcessingRunStatus.RUNNING.value
    return update


def route_after_event_resolution(
    state: RecruitmentGraphState,
) -> Literal["request_review", "plan_state_transition"]:
    if ProcessingRunStatus(state["status"]) is ProcessingRunStatus.NEEDS_REVIEW:
        return "request_review"
    return "plan_state_transition"


async def plan_state_transition(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.PLAN_STATE_TRANSITION
    await _advance(state, runtime, stage)
    plan = runtime.context.domain.plan_transition(
        _domain_evidence(state),
        ApplicationResolution.model_validate(state["application_resolution"]),
        EventResolution.model_validate(state["event_resolution"]),
    )
    if not plan.mutations_allowed:
        # Completing "successfully" here would silently drop the email's
        # interview or deadline. Fail visibly instead so the operator can act.
        raise TimeEvidenceUnresolvedError(plan.no_mutation_reason or "time_unresolved")
    return {
        "current_stage": stage.value,
        "transition_plan": plan.model_dump(mode="json"),
    }


async def persist_domain_changes(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.PERSIST_DOMAIN_CHANGES
    await _advance(state, runtime, stage)
    result = await runtime.context.domain.persist(
        DomainTransitionPlan.model_validate(state["transition_plan"])
    )
    return {
        "current_stage": stage.value,
        "application_id": (
            None if result.application_id is None else str(result.application_id)
        ),
        "event_id": None if result.event_id is None else str(result.event_id),
        "action_item_ids": [str(value) for value in result.action_item_ids],
    }


async def sync_calendar_placeholder(
    state: RecruitmentGraphState,
    runtime: Runtime[RecruitmentGraphContext],
) -> dict[str, object]:
    stage = WorkflowStage.SYNC_CALENDAR
    await _advance(state, runtime, stage)
    result = await runtime.context.calendar.sync(
        CalendarSyncRequest(
            account_id=UUID(state["account_id"]),
            source_email_id=_source_email_id(state),
            recruitment_event_id=(
                None if state.get("event_id") is None else UUID(state["event_id"])
            ),
            replace_missing_event=state.get("replace_missing_calendar_event", False),
            skip_update=state.get("skip_calendar_update", False),
        )
    )
    update: dict[str, object] = {
        "current_stage": stage.value,
        "calendar_operation": result.model_dump(mode="json"),
    }
    if result.needs_review:
        update.update(
            {
                "status": ProcessingRunStatus.NEEDS_REVIEW.value,
                "review_request": ReviewRequest(
                    review_type=ReviewType.UNSAFE_CALENDAR_UPDATE,
                    reason=result.reason,
                    question=(
                        "The proposed Calendar change is not safe to apply automatically. "
                        "Choose how this event should be handled."
                    ),
                    allowed_choices=(
                        "apply_proposed_update",
                        "skip_calendar_update",
                        "ignore",
                    ),
                ).model_dump(mode="json"),
                "review_resume_stage": stage.value,
            }
        )
    else:
        update["status"] = ProcessingRunStatus.RUNNING.value
    return update


def route_after_calendar(
    state: RecruitmentGraphState,
) -> Literal["request_review", "finalize_processing"]:
    if ProcessingRunStatus(state["status"]) is ProcessingRunStatus.NEEDS_REVIEW:
        return "request_review"
    return "finalize_processing"


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
