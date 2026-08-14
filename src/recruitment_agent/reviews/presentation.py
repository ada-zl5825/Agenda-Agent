"""Human-readable Review labels. Codes stay in storage; the UI never leads with them."""

from collections.abc import Mapping

from recruitment_agent.graph.contracts import (
    COMBINED_DATETIME_REASON,
    COMBINED_DEADLINE_REASON,
)

_ACTION_LABELS: dict[str, str] = {
    "TIMEZONE_AMBIGUITY": "确认时区",
    "DATETIME_CONFLICT": "确认时间",
    "APPLICATION_AMBIGUITY": "确认公司和申请",
    "UNCERTAIN_RESCHEDULE": "确认改期对象",
    "UNSAFE_CALENDAR_UPDATE": "确认日历更新",
}

_REASON_LABELS: dict[str, str] = {
    "timezone_ambiguity": "确认时区",
    COMBINED_DATETIME_REASON: "确认时区和开始时间",
    COMBINED_DEADLINE_REASON: "确认时区和截止日期",
    "datetime_unresolved": "补全面试开始时间",
    "deadline_unresolved": "补全截止日期",
    "datetime_conflict": "确认冲突时间",
    "extraction_needs_review": "确认抽出结果",
}

_EVENT_TYPE_LABELS: dict[str, str] = {
    "application_received": "投递回执",
    "assessment": "测评",
    "interview": "面试",
    "interview_reschedule": "面试改期",
    "action_required": "待办",
    "deadline": "截止日期",
    "result": "结果",
    "offer": "Offer",
    "rejection": "拒信",
    "general_update": "进展更新",
    "unknown": "待分类",
}

_FIELD_LABELS: dict[str, str] = {
    "subject": "主题",
    "sender_domain": "发件域名",
    "received_at": "收到时间",
    "open_original_email": "原邮件",
    "canonical_company": "公司",
    "company_raw": "原文公司",
    "company": "公司",
    "role_raw": "职位",
    "role": "职位",
    "status": "申请状态",
    "event_type": "事件类型",
    "interview_round": "面试轮次",
    "action_summary": "待办摘要",
    "meeting_platform": "会议平台",
    "location": "地点",
    "source_datetime_text": "原文开始时间",
    "source_deadline_text": "原文截止日期",
    "normalized_datetime": "抽出的开始时间",
    "normalized_deadline": "抽出的截止日期",
    "timezone_explicit": "邮件是否写明时区",
    "timezone_text": "原文时区",
    "datetime_confidence": "时间置信度",
    "company_confidence": "公司置信度",
    "event_confidence": "事件置信度",
    "validator_findings": "校验发现",
    "resolution": "处理结果",
    "resolved_at": "确认时间",
    "workflow_status": "工作流状态",
    "timezone": "时区",
}

_STATUS_LABELS: dict[str, str] = {
    "open": "待确认",
    "resolved": "已确认",
}

_CHOICE_LABELS: dict[str, str] = {
    "Europe/London": "伦敦 (Europe/London)",
    "Asia/Shanghai": "上海 (Asia/Shanghai)",
    "other": "其他 IANA 时区",
    "ignore": "忽略这封邮件",
    "use_override": "使用下面填写的时间",
    "use_extracted": "使用已抽出的时间",
    "create_new": "创建新申请",
    "accept": "接受抽出结果",
    "treat_as_new": "当作新面试",
    "apply_proposed_update": "按建议更新日历",
    "skip_calendar_update": "跳过日历更新",
}


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def review_action_label(review_type: str, reason: str) -> str:
    return _REASON_LABELS.get(reason) or _ACTION_LABELS.get(review_type) or "需要确认"


def event_type_label(event_type: str | None) -> str | None:
    if event_type is None:
        return None
    return _EVENT_TYPE_LABELS.get(event_type, event_type)


def review_headline(
    *,
    company: str | None,
    role: str | None,
    subject: str | None,
) -> str:
    parts = [part for part in (company, role) if part]
    if parts:
        return " · ".join(parts)
    if subject:
        return subject
    return "未识别的招聘邮件"


def headline_from_mappings(
    *,
    application: Mapping[str, object],
    extraction: Mapping[str, object],
    source: Mapping[str, object],
) -> str:
    company = _text(application.get("canonical_company")) or _text(
        application.get("company_raw")
    ) or _text(application.get("company")) or _text(extraction.get("company_raw"))
    role = (
        _text(application.get("role_raw"))
        or _text(application.get("role"))
        or _text(extraction.get("role_raw"))
    )
    return review_headline(
        company=company,
        role=role,
        subject=_text(source.get("subject")),
    )


def choice_label(choice: str, candidates: tuple[Mapping[str, object], ...] = ()) -> str:
    for candidate in candidates:
        if str(candidate.get("id")) == choice:
            company = _text(candidate.get("company"))
            role = _text(candidate.get("role"))
            if company and role:
                return f"{company} · {role}"
            return company or role or choice
    return _CHOICE_LABELS.get(choice, choice)


def clock_kind(reason: str) -> str | None:
    """Return 'start' or 'deadline' when the review asks for a wall-clock."""
    if reason in {COMBINED_DEADLINE_REASON, "deadline_unresolved"}:
        return "deadline"
    if reason in {COMBINED_DATETIME_REASON, "datetime_unresolved"}:
        return "start"
    return None


def field_label(key: str) -> str:
    return _FIELD_LABELS.get(key, key)


def review_status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


def clock_field_copy(reason: str) -> tuple[str, str]:
    """Return (label, hint) for a human-entered local clock."""
    if clock_kind(reason) == "deadline":
        return (
            "截止日期",
            "这是测评或材料的到期时间, 不是面试结束时间. 格式 YYYY-MM-DD HH:MM.",
        )
    return (
        "开始时间",
        "这是面试或事件的开始时间, 不是结束时间. 格式 YYYY-MM-DD HH:MM.",
    )
