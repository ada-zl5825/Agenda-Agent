"""Human-readable Daily Brief labels for the console preview."""

from recruitment_agent.briefs.models import BriefSection

_SECTION_LABELS: dict[BriefSection, str] = {
    BriefSection.TODAY: "今天",
    BriefSection.NEXT_48_HOURS: "未来 48 小时",
    BriefSection.ASSESSMENTS: "测评",
    BriefSection.UPCOMING_INTERVIEWS: "即将面试",
    BriefSection.ACTION_REQUIRED: "需要行动",
    BriefSection.NEW_UPDATES: "新进展",
    BriefSection.WAITING_FOR_RESULT: "等待结果",
    BriefSection.NEEDS_REVIEW: "待确认",
}


def brief_section_label(section: BriefSection) -> str:
    return _SECTION_LABELS.get(section, section.value)
