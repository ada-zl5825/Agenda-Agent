"""Escaped HTML rendering for authenticated Review pages."""

from collections.abc import Mapping
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlsplit

from recruitment_agent.privacy.sanitizer import PrivacySanitizer
from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem
from recruitment_agent.reviews.presentation import (
    choice_label,
    clock_field_copy,
    clock_kind,
    event_type_label,
    headline_from_mappings,
    review_action_label,
    review_headline,
)

_SUBJECT_SANITIZER = PrivacySanitizer()


class ReviewHtmlRenderer:
    def queue(self, items: tuple[ReviewQueueItem, ...]) -> str:
        cards = "".join(self._queue_card(item) for item in items) or (
            "<p>当前没有待确认的邮件。</p>"
        )
        return self._page(
            "待确认",
            '<nav><a href="/agent">控制台</a> &middot; '
            '<a href="/brief/today">今日 Brief</a></nav>'
            f"<h1>待确认</h1>{cards}",
        )

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
        header = self._table(
            {
                "需要确认": action,
                "状态": detail.status,
                "等待时长": age,
                "内部类型": detail.review_type,
                "原因码": detail.reason,
            }
        )
        source_values = dict(detail.source)
        raw_subject = source_values.get("subject")
        if isinstance(raw_subject, str):
            source_values["subject"] = _SUBJECT_SANITIZER.sanitize(raw_subject).text
        source = self._table(source_values, url_fields={"open_original_email"})
        application = self._table(detail.application)
        extracted = self._table(
            {
                key: detail.extraction.get(key)
                for key in (
                    "event_type",
                    "interview_round",
                    "action_summary",
                    "meeting_platform",
                    "location",
                )
            }
        )
        time_evidence = self._table(
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
            }
        )
        confidence = self._table(
            {
                "company_confidence": detail.extraction.get("company_confidence"),
                "event_confidence": detail.extraction.get("event_confidence"),
                "validator_findings": ", ".join(detail.validation_findings) or None,
            }
        )
        diff = (
            "<h3>Current</h3>"
            + self._table(detail.current_values)
            + "<h3>Proposed</h3>"
            + self._table(detail.proposed_values)
            + "<h3>Field differences</h3>"
            + self._diff_table(detail.current_values, detail.proposed_values)
        )
        candidates = "".join(self._table(candidate) for candidate in detail.candidates)
        links = "".join(self._table(link) for link in detail.secure_links)
        effects = (
            "<ul>"
            + "".join(f"<li>{escape(effect)}</li>" for effect in detail.side_effects)
            + "</ul>"
        )
        decision = self._decision(detail, csrf_token)
        audit = self._table(
            {
                "resolution": detail.resolution,
                "resolved_at": detail.resolved_at,
                "workflow_status": detail.run_status,
            }
        )
        banner = (
            f'<p class="error">处理失败: {escape(error)}</p>'
            if error
            else ""
        )
        content = (
            '<nav><a href="/agent">控制台</a> &middot; '
            '<a href="/reviews">&larr; 待确认</a></nav>'
            f"<h1>{escape(headline)}</h1>"
            f'<p class="lead">{escape(action)}</p>'
            + banner
            + self._section("本次要确认什么", header)
            + self._section("来源邮件", source)
            + self._section("申请", application)
            + self._section("抽出的事件", extracted)
            + self._section("时间证据", time_evidence)
            + self._section("其他置信度与校验", confidence)
            + self._section("现有记录 vs 建议", diff)
            + self._section("候选匹配", candidates or "<p>未提供</p>")
            + self._section("安全链接", links or "<p>未提供</p>")
            + self._section("副作用预览", effects)
            + self._section("决定", decision)
            + self._section("处理记录", audit)
        )
        return self._page(headline, content)

    def _queue_card(self, item: ReviewQueueItem) -> str:
        headline = review_headline(
            company=item.company,
            role=item.role,
            subject=item.subject,
        )
        action = review_action_label(item.review_type, item.reason)
        event = event_type_label(item.event_type)
        bits = [action]
        if event:
            bits.append(event)
        if item.source_time_text:
            bits.append(item.source_time_text)
        return (
            '<article class="card">'
            f'<a href="/reviews/{item.id}"><strong>{escape(headline)}</strong></a>'
            f"<p>{escape(' · '.join(bits))}</p>"
            f'<p class="meta">{escape(self._age(item.created_at, datetime.now(UTC)))}</p>'
            "</article>"
        )

    def _decision(self, detail: ReviewDetail, csrf_token: str) -> str:
        if detail.status != "open":
            return "<p>这条已经确认, 只读.</p>"
        choices = "".join(
            '<label class="choice">'
            f'<input type="radio" name="choice" value="{escape(choice, quote=True)}" required>'
            f" {escape(choice_label(choice, detail.candidates))}</label>"
            for choice in detail.allowed_choices
        )
        extras = ""
        if "other" in detail.allowed_choices:
            extras += (
                '<label>其他时区 <input name="override_value" autocomplete="off" '
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
                f"<label>{escape(label)} "
                f'<input name="{field_name}" autocomplete="off" '
                'placeholder="YYYY-MM-DD HH:MM"></label>'
                f'<p class="hint">{escape(hint)}</p>'
            )
        return (
            f"<p>{escape(detail.question)}</p>"
            f'<form method="post" action="/reviews/{detail.id}/resolve">'
            f'<input type="hidden" name="csrf_token" '
            f'value="{escape(csrf_token, quote=True)}">'
            f'<input type="hidden" name="expected_version" value="{detail.version}">'
            f"{choices}{extras}<button type=\"submit\">确认并继续</button></form>"
        )

    def _table(
        self,
        values: Mapping[str, object],
        *,
        url_fields: set[str] | None = None,
    ) -> str:
        urls = url_fields or set()
        rows: list[str] = []
        for key, raw in values.items():
            rendered = self._value(raw)
            if key in urls and isinstance(raw, str) and self._safe_url(raw):
                rendered = f'<a href="{escape(raw, quote=True)}">打开原邮件</a>'
            rows.append(f"<tr><th>{escape(key)}</th><td>{rendered}</td></tr>")
        return '<table class="data">' + "".join(rows) + "</table>"

    def _diff_table(
        self,
        current: Mapping[str, object],
        proposed: Mapping[str, object],
    ) -> str:
        rows = []
        for key in sorted(set(current) | set(proposed)):
            before = current.get(key)
            after = proposed.get(key)
            changed = "yes" if before != after else "no"
            rows.append(
                "<tr>"
                f"<th>{escape(key)}</th>"
                f"<td>{self._value(before)}</td>"
                f"<td>{self._value(after)}</td>"
                f"<td>{changed}</td>"
                "</tr>"
            )
        return (
            '<table class="data"><thead><tr><th>field</th><th>current</th>'
            '<th>proposed</th><th>changed</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table>"
        )

    @staticmethod
    def _value(value: object) -> str:
        if value is None or value == "" or value == [] or value == {}:
            return "未提供"
        if isinstance(value, dict):
            return escape(", ".join(f"{key}={val}" for key, val in value.items()))
        return escape(str(value))

    @staticmethod
    def _safe_url(value: str) -> bool:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and parsed.hostname in {
            "outlook.office.com",
            "outlook.office365.com",
            "outlook.live.com",
        }

    @staticmethod
    def _age(created_at: datetime, now: datetime) -> str:
        seconds = max(0, int((now - created_at).total_seconds()))
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        return f"{hours}h {minutes}m"

    @staticmethod
    def _section(title: str, content: str) -> str:
        return f"<section><h2>{escape(title)}</h2>{content}</section>"

    @staticmethod
    def _page(title: str, content: str) -> str:
        return (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(title)}</title>"
            "<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:980px;"
            "margin:24px auto;padding:0 16px;color:#111827}section,.card{"
            "border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:14px 0}"
            ".data{border-collapse:collapse;width:100%}.data th,.data td{"
            "border-bottom:1px solid #eee;text-align:left;padding:8px;vertical-align:top}"
            ".choice{display:block;padding:8px}button{margin-top:12px;"
            "padding:10px 18px}.error{color:#991b1b;background:#fef2f2;"
            "border:1px solid #fecaca;border-radius:8px;padding:10px 12px}"
            ".lead{color:#374151;font-size:1.05rem}.meta,.hint{color:#6b7280}"
            "label{display:block;margin:12px 0 6px}input[type=text],input:not([type]){"
            "width:min(360px,100%);padding:8px}"
            "</style></head><body>"
            f"{content}</body></html>"
        )
