"""Escaped HTML rendering for authenticated Review pages."""

from collections.abc import Mapping
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlsplit

from recruitment_agent.privacy.sanitizer import PrivacySanitizer
from recruitment_agent.reviews.models import ReviewDetail, ReviewQueueItem

_SUBJECT_SANITIZER = PrivacySanitizer()


class ReviewHtmlRenderer:
    def queue(self, items: tuple[ReviewQueueItem, ...]) -> str:
        cards = "".join(
            (
                '<article class="card">'
                f'<a href="/reviews/{item.id}"><strong>{escape(item.review_type)}</strong></a>'
                f"<p>{self._optional_text(item.company)} &middot; "
                f"{self._optional_text(item.role)}</p>"
                f"<p>{escape(item.reason)} &middot; "
                f"{escape(item.created_at.isoformat())}</p>"
                "</article>"
            )
            for item in items
        ) or "<p>No open reviews.</p>"
        return self._page(
            "Reviews",
            '<nav><a href="/agent">Agent console</a> &middot; '
            '<a href="/brief/today">Today\'s Brief</a></nav>'
            f"<h1>Reviews</h1>{cards}",
        )

    def detail(
        self,
        detail: ReviewDetail,
        *,
        csrf_token: str,
        error: str | None = None,
    ) -> str:
        age = self._age(detail.created_at, detail.resolved_at or datetime.now(UTC))
        header = self._table(
            {
                "review_id": str(detail.id),
                "review_type": detail.review_type,
                "status": detail.status,
                "reason_code": detail.reason,
                "created_at": detail.created_at,
                "pending_age": age,
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
            f'<p class="error">Workflow failed: {escape(error)}</p>'
            if error
            else ""
        )
        content = (
            '<nav><a href="/agent">Agent console</a> &middot; '
            '<a href="/reviews">&larr; Reviews</a></nav><h1>Review detail</h1>'
            + banner
            + self._section("Header", header)
            + self._section("Source email", source)
            + self._section("Application", application)
            + self._section("Extracted event", extracted)
            + self._section("Time evidence", time_evidence)
            + self._section("Other confidence and validator findings", confidence)
            + self._section("Existing vs proposed", diff)
            + self._section("Candidate matches", candidates or "<p>&#26410;&#25552;&#20379;</p>")
            + self._section("Secure links", links or "<p>&#26410;&#25552;&#20379;</p>")
            + self._section("Side-effect preview", effects)
            + self._section("Decision", decision)
            + self._section("Resolution audit", audit)
        )
        return self._page(f"Review {detail.id}", content)

    def _decision(self, detail: ReviewDetail, csrf_token: str) -> str:
        if detail.status != "open":
            return "<p>This review is resolved and read-only.</p>"
        choices = "".join(
            '<label class="choice">'
            f'<input type="radio" name="choice" value="{escape(choice, quote=True)}" required>'
            f" {escape(choice)}</label>"
            for choice in detail.allowed_choices
        )
        override = (
            '<label>Typed override <input name="override_value" autocomplete="off" '
            'placeholder="YYYY-MM-DD HH:MM or IANA timezone"></label>'
            if {"other", "use_override"} & set(detail.allowed_choices)
            else ""
        )
        return (
            f"<p>{escape(detail.question)}</p>"
            f'<form method="post" action="/reviews/{detail.id}/resolve">'
            f'<input type="hidden" name="csrf_token" '
            f'value="{escape(csrf_token, quote=True)}">'
            f'<input type="hidden" name="expected_version" value="{detail.version}">'
            f'{choices}{override}<button type="submit">Resolve</button></form>'
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
                rendered = f'<a href="{escape(raw, quote=True)}">Open original email</a>'
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
            return "&#26410;&#25552;&#20379;"
        if isinstance(value, dict):
            return escape(", ".join(f"{key}={val}" for key, val in value.items()))
        return escape(str(value))

    @staticmethod
    def _optional_text(value: str | None) -> str:
        return escape(value) if value else "&#26410;&#25552;&#20379;"

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
            "</style></head><body>"
            f"{content}</body></html>"
        )
