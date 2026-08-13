"""LLM-free Daily Brief HTML and plain-text rendering."""

from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from recruitment_agent.briefs.models import SECTION_ORDER, BriefItem, DailyBriefSnapshot


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
                f'<section><h2 style="color:#1f2937">{escape(section.value)}</h2>'
                + "".join(self._html_item(item, timezone) for item in items)
                + "</section>"
            )
            text_sections.append(
                section.value
                + "\n\n"
                + "\n\n".join(self._text_item(item, timezone) for item in items)
            )
        if not html_sections:
            html_sections.append("<p>No recruitment items require attention today.</p>")
            text_sections.append("No recruitment items require attention today.")
        html = (
            '<!doctype html><html><body style="font-family:Segoe UI,Arial,sans-serif;'
            'max-width:720px;margin:24px auto;color:#111827">'
            f"<h1>Recruitment Brief</h1><p>{escape(snapshot.brief_date.isoformat())}</p>"
            + "".join(html_sections)
            + "</body></html>"
        )
        text = f"Recruitment Brief\n{snapshot.brief_date.isoformat()}\n\n" + "\n\n".join(
            text_sections
        )
        return RenderedBrief(subject=subject, html=html, text=text)

    def _html_item(self, item: BriefItem, timezone: ZoneInfo) -> str:
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
            '<article style="border:1px solid #e5e7eb;border-radius:8px;padding:14px;'
            'margin:10px 0">'
            + "<br>".join(rows)
            + (f'<p style="margin-bottom:0">{" · ".join(links)}</p>' if links else "")
            + "</article>"
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
        return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'
