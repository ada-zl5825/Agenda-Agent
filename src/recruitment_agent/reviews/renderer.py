"""Escaped HTML rendering for authenticated Review pages."""

from collections.abc import Mapping
from datetime import UTC, datetime
from html import escape
from typing import ClassVar

from recruitment_agent.dashboard.chrome import (
    console_banner,
    console_hero,
    console_metric,
    console_page,
    console_section,
    console_table,
    console_value,
)
from recruitment_agent.privacy.sanitizer import PrivacySanitizer
from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem
from recruitment_agent.reviews.presentation import (
    choice_label,
    clock_field_copy,
    clock_kind,
    event_type_label,
    field_label,
    headline_from_mappings,
    review_action_label,
    review_headline,
    review_status_label,
)

_SUBJECT_SANITIZER = PrivacySanitizer()


class ReviewHtmlRenderer:
    _ERRORS: ClassVar[dict[str, str]] = {
        "EVENT_DATETIME_UNRESOLVED": "填写的时间无法使用, 请按 YYYY-MM-DD HH:MM 重试.",
        "EVENT_TIME_UNRESOLVED": "时间证据仍无法使用, 请刷新后重试.",
        "REVIEW_CONFLICT": "这条 Review 已变化, 请刷新后重试.",
        "REVIEW_NOT_FOUND": "找不到这条 Review.",
        "CSRF_INVALID": "页面已过期, 请刷新后重试.",
    }

    def queue(self, items: tuple[ReviewQueueItem, ...]) -> str:
        open_count = len(items)
        metrics = (
            '<div class="metrics">'
            + console_metric("待确认", str(open_count), open_count == 0)
            + console_metric(
                "时区",
                str(sum(1 for item in items if "timezone" in item.reason)),
                True,
            )
            + console_metric(
                "时间",
                str(
                    sum(
                        1
                        for item in items
                        if "datetime" in item.reason or "deadline" in item.reason
                    )
                ),
                True,
            )
            + console_metric(
                "申请 / 日历",
                str(
                    sum(
                        1
                        for item in items
                        if item.review_type
                        in {
                            "APPLICATION_AMBIGUITY",
                            "UNCERTAIN_RESCHEDULE",
                            "UNSAFE_CALENDAR_UPDATE",
                        }
                    )
                ),
                True,
            )
            + "</div>"
        )
        cards = "".join(self._queue_card(item) for item in items) or (
            '<p class="empty">当前没有待确认的邮件.</p>'
        )
        content = (
            console_hero(
                eyebrow="RECRUITMENT INBOX AGENT",
                title="待确认",
                subtitle="只处理真正需要人工判断的时区、时间和申请匹配.",
                state_label="队列已清空" if open_count == 0 else f"{open_count} 条待处理",
                ok=open_count == 0,
            )
            + console_section(
                "Review 队列",
                metrics + '<div class="queue-list">' + cards + "</div>",
                "标题优先显示公司和职位; 错误码不会出现在主文案里.",
            )
        )
        return console_page("待确认", content, nav="reviews")

    def detail(
        self,
        detail: ReviewDetail,
        *,
        csrf_token: str,
        error: str | None = None,
    ) -> str:
        age = self._age(detail.created_at, detail.resolved_at or datetime.now(UTC))
        headline = headline_from_mappings(
            application=detail.application,
            extraction=detail.extraction,
            source=detail.source,
        )
        action = review_action_label(detail.review_type, detail.reason)
        open_item = detail.status == "open"
        source_values = dict(detail.source)
        raw_subject = source_values.get("subject")
        if isinstance(raw_subject, str):
            source_values["subject"] = _SUBJECT_SANITIZER.sanitize(raw_subject).text
        banner = console_banner(error=self._error_text(error))
        header = console_table(
            {
                "需要确认": action,
                "状态": review_status_label(detail.status),
                "等待时长": age,
                "内部类型": detail.review_type,
                "原因码": detail.reason,
            }
        )
        extracted = console_table(
            {
                key: self._display(key, detail.extraction.get(key))
                for key in (
                    "event_type",
                    "interview_round",
                    "action_summary",
                    "meeting_platform",
                    "location",
                )
            },
            labels={key: field_label(key) for key in (
                "event_type",
                "interview_round",
                "action_summary",
                "meeting_platform",
                "location",
            )},
        )
        time_evidence = console_table(
            {
                key: detail.extraction.get(key)
                for key in (
                    "source_datetime_text",
                    "source_deadline_text",
                    "normalized_datetime",
                    "normalized_deadline",
                    "timezone_explicit",
                    "timezone_text",
                    "datetime_confidence",
                )
            },
            labels={
                key: field_label(key)
                for key in (
                    "source_datetime_text",
                    "source_deadline_text",
                    "normalized_datetime",
                    "normalized_deadline",
                    "timezone_explicit",
                    "timezone_text",
                    "datetime_confidence",
                )
            },
        )
        confidence = console_table(
            {
                "company_confidence": detail.extraction.get("company_confidence"),
                "event_confidence": detail.extraction.get("event_confidence"),
                "validator_findings": ", ".join(detail.validation_findings) or None,
            },
            labels={
                "company_confidence": field_label("company_confidence"),
                "event_confidence": field_label("event_confidence"),
                "validator_findings": field_label("validator_findings"),
            },
        )
        diff = (
            '<div class="two-col">'
            + '<article class="count-card"><h3>当前记录</h3>'
            + console_table(detail.current_values, labels=self._labels(detail.current_values))
            + "</article>"
            + '<article class="count-card"><h3>建议结果</h3>'
            + console_table(detail.proposed_values, labels=self._labels(detail.proposed_values))
            + "</article></div>"
            + self._diff_table(detail.current_values, detail.proposed_values)
        )
        candidates = "".join(
            console_table(candidate, labels=self._labels(candidate))
            for candidate in detail.candidates
        )
        links = "".join(
            console_table(link, labels=self._labels(link)) for link in detail.secure_links
        )
        effects = (
            "<ul>"
            + "".join(f"<li>{escape(effect)}</li>" for effect in detail.side_effects)
            + "</ul>"
        )
        content = (
            '<p class="crumb"><a href="/reviews">待确认</a><span class="muted">/</span>'
            f"<span>{escape(headline)}</span></p>"
            + console_hero(
                eyebrow="RECRUITMENT INBOX AGENT",
                title=headline,
                subtitle=action,
                state_label=review_status_label(detail.status),
                ok=not open_item,
            )
            + banner
            + console_section(
                "决定",
                self._decision(detail, csrf_token),
                "确认后会继续同一封邮件的下一条 Review.",
            )
            + console_section("本次要确认什么", header)
            + '<div class="two-col">'
            + console_section(
                "来源邮件",
                console_table(
                    source_values,
                    labels=self._labels(source_values),
                    url_fields={"open_original_email": "打开原邮件"},
                ),
            )
            + console_section(
                "申请",
                console_table(detail.application, labels=self._labels(detail.application)),
            )
            + "</div>"
            + '<div class="two-col">'
            + console_section("抽出的事件", extracted)
            + console_section("时间证据", time_evidence)
            + "</div>"
            + console_section("现有记录 vs 建议", diff)
            + (
                console_section("候选匹配", candidates)
                if candidates
                else ""
            )
            + (console_section("安全链接", links) if links else "")
            + console_section("副作用预览", effects)
            + console_section("其他置信度与校验", confidence)
            + console_section(
                "处理记录",
                console_table(
                    {
                        "resolution": detail.resolution,
                        "resolved_at": detail.resolved_at,
                        "workflow_status": detail.run_status,
                    },
                    labels={
                        "resolution": field_label("resolution"),
                        "resolved_at": field_label("resolved_at"),
                        "workflow_status": field_label("workflow_status"),
                    },
                ),
            )
        )
        return console_page(headline, content, nav="reviews")

    def _queue_card(self, item: ReviewQueueItem) -> str:
        headline = review_headline(
            company=item.company,
            role=item.role,
            subject=item.subject,
        )
        action = review_action_label(item.review_type, item.reason)
        event = event_type_label(item.event_type)
        bits = [bit for bit in (event, item.source_time_text) if bit]
        return (
            '<article class="review-card"><div>'
            '<div class="switch-title"><span class="indicator off"></span>'
            f"<h3>{escape(headline)}</h3>"
            f'<span class="pill paused">{escape(action)}</span></div>'
            + (f"<p>{escape(' · '.join(bits))}</p>" if bits else "")
            + (
                '<p class="section-note">已等待 '
                f"{escape(self._age(item.created_at, datetime.now(UTC)))}</p>"
            )
            + "</div>"
            + f'<a class="button primary" href="/reviews/{item.id}">打开</a></article>'
        )

    def _decision(self, detail: ReviewDetail, csrf_token: str) -> str:
        if detail.status != "open":
            return '<p class="empty">这条已经确认, 当前只读.</p>'
        choices = "".join(
            '<label class="choice">'
            f'<input type="radio" name="choice" value="{escape(choice, quote=True)}" required>'
            f" {escape(choice_label(choice, detail.candidates))}</label>"
            for choice in detail.allowed_choices
        )
        extras = ""
        if "other" in detail.allowed_choices:
            extras += (
                '<label class="field">其他时区'
                '<input type="text" name="override_value" autocomplete="off" '
                'placeholder="例如 Asia/Shanghai"></label>'
            )
        kind = clock_kind(detail.reason)
        if kind is not None or "use_override" in detail.allowed_choices:
            label, hint = clock_field_copy(detail.reason)
            field_name = "override_value"
            if kind is not None and "use_override" not in detail.allowed_choices:
                field_name = "clock_override"
            if "other" in detail.allowed_choices:
                field_name = "clock_override"
            extras += (
                f'<label class="field">{escape(label)}'
                f'<input type="text" name="{field_name}" autocomplete="off" '
                'placeholder="YYYY-MM-DD HH:MM"></label>'
                f'<p class="hint">{escape(hint)}</p>'
            )
        return (
            f'<p class="question">{escape(detail.question)}</p>'
            f'<form class="decision-form" method="post" action="/reviews/{detail.id}/resolve">'
            f'<input type="hidden" name="csrf_token" '
            f'value="{escape(csrf_token, quote=True)}">'
            f'<input type="hidden" name="expected_version" value="{detail.version}">'
            f'<div class="choice-list">{choices}</div>{extras}'
            '<button class="button primary" type="submit">确认并继续</button></form>'
        )

    def _diff_table(
        self,
        current: Mapping[str, object],
        proposed: Mapping[str, object],
    ) -> str:
        rows = []
        for key in sorted(set(current) | set(proposed)):
            before = current.get(key)
            after = proposed.get(key)
            changed = before != after
            tone = ' class="diff-changed"' if changed else ""
            rows.append(
                f"<tr{tone}>"
                f"<th>{escape(field_label(key))}</th>"
                f"<td>{console_value(before)}</td>"
                f"<td>{console_value(after)}</td>"
                f"<td>{'是' if changed else '否'}</td>"
                "</tr>"
            )
        return (
            '<div class="table-wrap"><table><thead><tr><th>字段</th><th>当前</th>'
            "<th>建议</th><th>是否变化</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )

    def _error_text(self, error: str | None) -> str | None:
        if error is None or error == "":
            return None
        return self._ERRORS.get(error, f"处理失败: {error}")

    @staticmethod
    def _display(key: str, value: object) -> object:
        if key == "event_type" and isinstance(value, str):
            return event_type_label(value) or value
        return value

    @staticmethod
    def _labels(values: Mapping[str, object]) -> dict[str, str]:
        return {key: field_label(key) for key in values}

    @staticmethod
    def _age(created_at: datetime, now: datetime) -> str:
        seconds = max(0, int((now - created_at).total_seconds()))
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        return f"{hours}h {minutes}m"
