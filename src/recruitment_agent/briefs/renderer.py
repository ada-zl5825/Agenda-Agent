"""LLM-free Daily Brief HTML and plain-text rendering."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from recruitment_agent.briefs.models import SECTION_ORDER, BriefItem, DailyBriefSnapshot
from recruitment_agent.briefs.presentation import brief_section_label
from recruitment_agent.dashboard.chrome import (
    console_hero,
    console_metric,
    console_page,
    console_section,
)


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class RenderedBrief:
    subject: str
    html: str
    text: str

    def __repr__(self) -> str:
        return f"RenderedBrief(subject={self.subject!r}, html_bytes={len(self.html)})"


class DailyBriefRenderer:
    """Render exact stored values; never infer or rewrite recruitment facts."""

    def render(self, snapshot: DailyBriefSnapshot) -> RenderedBrief:
        timezone = ZoneInfo(snapshot.timezone)
        subject = f"Recruitment Brief | {snapshot.brief_date.isoformat()}"
        html_sections: list[str] = []
        text_sections: list[str] = []
        for section in SECTION_ORDER:
            items = tuple(item for item in snapshot.items if item.section is section)
            if not items:
                continue
            html_sections.append(
                '<tr><td style="padding:0 0 18px 0">'
                f'<h2 style="margin:0 0 10px;color:#10233f;font-size:16px">'
                f"{escape(section.value)}</h2>"
                + "".join(self._email_item(item, timezone) for item in items)
                + "</td></tr>"
            )
            text_sections.append(
                section.value
                + "\n\n"
                + "\n\n".join(self._text_item(item, timezone) for item in items)
            )
        if not html_sections:
            html_sections.append(
                '<tr><td style="padding:18px 0;color:#64748b">'
                "No recruitment items require attention today.</td></tr>"
            )
            text_sections.append("No recruitment items require attention today.")
        html = (
            '<!doctype html><html><body style="margin:0;background:#f3f6fa;'
            'font-family:Segoe UI,Arial,sans-serif;color:#10233f">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="background:#f3f6fa"><tr><td align="center" style="padding:24px 12px">'
            '<table role="presentation" width="640" cellpadding="0" cellspacing="0" '
            'style="max-width:640px;width:100%">'
            '<tr><td style="background:#071a34;color:#fff;padding:22px 24px;'
            'border-radius:16px 16px 0 0">'
            '<p style="margin:0 0 8px;color:#8eb6f0;font-size:11px;font-weight:800;'
            'letter-spacing:.14em">RECRUITMENT INBOX AGENT</p>'
            "<h1 style=\"margin:0;font-size:28px\">Recruitment Brief</h1>"
            f'<p style="margin:10px 0 0;color:#c9d8eb">'
            f"{escape(snapshot.brief_date.isoformat())}</p>"
            "</td></tr>"
            '<tr><td style="background:#fff;padding:22px 24px;border:1px solid #dce4ef;'
            'border-top:0;border-radius:0 0 16px 16px">'
            + "".join(html_sections)
            + "</td></tr></table></td></tr></table></body></html>"
        )
        text = f"Recruitment Brief\n{snapshot.brief_date.isoformat()}\n\n" + "\n\n".join(
            text_sections
        )
        return RenderedBrief(subject=subject, html=html, text=text)

    def render_console(self, snapshot: DailyBriefSnapshot) -> str:
        timezone = ZoneInfo(snapshot.timezone)
        counts = Counter(item.section for item in snapshot.items)
        metrics = "".join(
            console_metric(
                brief_section_label(section),
                str(counts[section]),
                counts[section] == 0,
            )
            for section in SECTION_ORDER
            if counts[section]
        )
        if not metrics:
            metrics = console_metric("今日事项", "0", True)
        sections = []
        for section in SECTION_ORDER:
            items = tuple(item for item in snapshot.items if item.section is section)
            if not items:
                continue
            cards = "".join(self._console_item(item, timezone) for item in items)
            sections.append(
                console_section(
                    brief_section_label(section),
                    '<div class="queue-list">' + cards + "</div>",
                    f"{len(items)} 项 · {section.value}",
                )
            )
        body = (
            "".join(sections)
            if sections
            else console_section(
                "今日事项",
                '<p class="empty">今天没有需要关注的招聘事项.</p>',
            )
        )
        content = (
            console_hero(
                eyebrow="RECRUITMENT INBOX AGENT",
                title="今日 Daily Brief",
                subtitle=f"{snapshot.brief_date.isoformat()} · {snapshot.timezone}",
                state_label=(
                    "无需处理" if not snapshot.items else f"{len(snapshot.items)} 项"
                ),
                ok=not snapshot.items,
            )
            + console_section(
                "分组概览",
                '<div class="metrics">' + metrics + "</div>",
                "预览使用与邮件相同的 PostgreSQL 快照; 不改写招聘事实.",
            )
            + body
        )
        return console_page("今日 Daily Brief", content, nav="brief")

    def _email_item(self, item: BriefItem, timezone: ZoneInfo) -> str:
        title = " | ".join(value for value in (item.company, item.role) if value) or item.stage
        rows = [f"<strong>{escape(title)}</strong>", escape(item.stage)]
        if item.starts_at is not None:
            rows.append(f"Starts: {escape(self._format_time(item.starts_at, timezone))}")
        if item.deadline_at is not None:
            rows.append(f"Deadline: {escape(self._format_time(item.deadline_at, timezone))}")
        if item.detail:
            rows.append(escape(item.detail))
        links: list[str] = []
        if item.review_id is not None and item.review_url is not None:
            links.append(self._link(item.review_url, "Open Review"))
        elif item.action_url is not None and item.action_label is not None:
            links.append(self._link(item.action_url.get_secret_value(), item.action_label))
        if item.original_email_url is not None:
            links.append(self._link(item.original_email_url, "Open original email"))
        return (
            '<div style="border:1px solid #dce4ef;border-radius:12px;padding:14px;'
            'margin:0 0 10px;background:#f8fafc">'
            + "<br>".join(rows)
            + (
                f'<p style="margin:10px 0 0">{" · ".join(links)}</p>'
                if links
                else ""
            )
            + "</div>"
        )

    def _console_item(self, item: BriefItem, timezone: ZoneInfo) -> str:
        title = " · ".join(value for value in (item.company, item.role) if value) or item.stage
        facts: list[str] = []
        if item.starts_at is not None:
            facts.append(f"开始时间 {self._format_time(item.starts_at, timezone)}")
        if item.deadline_at is not None:
            facts.append(f"截止日期 {self._format_time(item.deadline_at, timezone)}")
        if item.detail:
            facts.append(item.detail)
        links: list[str] = []
        if item.review_id is not None and item.review_url is not None:
            parsed = urlsplit(item.review_url)
            if parsed.scheme in {"http", "https"} and parsed.hostname is not None:
                links.append(
                    f'<a class="button primary" href="{escape(item.review_url, quote=True)}">'
                    "打开 Review</a>"
                )
        elif item.action_url is not None and item.action_label is not None:
            links.append(
                self._link(item.action_url.get_secret_value(), item.action_label)
            )
        if item.original_email_url is not None:
            links.append(self._link(item.original_email_url, "打开原邮件"))
        return (
            '<article class="brief-item"><div>'
            f"<h3>{escape(title)}</h3>"
            f'<div class="review-meta"><span class="pill paused">{escape(item.stage)}</span></div>'
            + (f"<p>{escape(' · '.join(facts))}</p>" if facts else "")
            + (
                f'<div class="brief-links">{"".join(links)}</div>'
                if links
                else ""
            )
            + "</div></article>"
        )

    def _text_item(self, item: BriefItem, timezone: ZoneInfo) -> str:
        lines = [value for value in (item.company, item.role, item.stage) if value]
        if item.starts_at is not None:
            lines.append(f"Starts: {self._format_time(item.starts_at, timezone)}")
        if item.deadline_at is not None:
            lines.append(f"Deadline: {self._format_time(item.deadline_at, timezone)}")
        if item.detail:
            lines.append(item.detail)
        if item.review_id is not None and item.review_url is not None:
            lines.append(f"Open Review: {item.review_url}")
        elif item.action_url is not None and item.action_label is not None:
            lines.append(f"{item.action_label}: {item.action_url.get_secret_value()}")
        if item.original_email_url is not None:
            lines.append(f"Open original email: {item.original_email_url}")
        return "\n".join(lines)

    @staticmethod
    def _format_time(value: datetime, timezone: ZoneInfo) -> str:
        return value.astimezone(timezone).strftime("%Y-%m-%d %H:%M %Z")

    @staticmethod
    def _link(url: str, label: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return escape(label)
        # Secret-bearing action URLs must not leak through the Referer header
        # when the recipient clicks through to a third-party site.
        return (
            f'<a href="{escape(url, quote=True)}" rel="noreferrer noopener" '
            f'referrerpolicy="no-referrer">{escape(label)}</a>'
        )
