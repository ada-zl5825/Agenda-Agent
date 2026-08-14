"""Shared visual chrome for the Agent console, Review, and Brief preview."""

# Long lines are kept for the dependency-free inline CSS template.
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from html import escape
from urllib.parse import urlsplit

_NAV: tuple[tuple[str, str, str], ...] = (
    ("agent", "/agent", "控制台"),
    ("reviews", "/reviews", "Reviews"),
    ("brief", "/brief/today", "今日 Brief"),
)

_OUTLOOK_HOSTS = frozenset(
    {"outlook.office.com", "outlook.office365.com", "outlook.live.com"}
)


def console_page(
    title: str,
    content: str,
    *,
    nav: str,
    auto_refresh: str = "",
) -> str:
    links = "".join(
        f'<a href="{href}" class="{"active" if key == nav else ""}">{escape(label)}</a>'
        for key, href, label in _NAV
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"{auto_refresh}<title>{escape(title)}</title>"
        f"<style>{_CONSOLE_CSS}</style></head><body>"
        '<nav class="topbar"><div class="topbar-inner">'
        '<a class="brand" href="/agent" style="color:white">Agenda Agent</a>'
        f'<div class="nav">{links}</div></div></nav>'
        f'<main class="shell">{content}</main></body></html>'
    )


def console_hero(
    *,
    eyebrow: str,
    title: str,
    subtitle: str,
    state_label: str,
    ok: bool,
) -> str:
    tone = "ok" if ok else "warn"
    return (
        '<header class="hero">'
        f'<div><p class="eyebrow">{escape(eyebrow)}</p>'
        f"<h1>{escape(title)}</h1>"
        f'<p class="subtitle">{escape(subtitle)}</p></div>'
        f'<span class="state {tone}"><span class="dot"></span>{escape(state_label)}</span>'
        "</header>"
    )


def console_section(title: str, content: str, subtitle: str | None = None) -> str:
    description = (
        "" if subtitle is None else f'<p class="section-note">{escape(subtitle)}</p>'
    )
    return (
        '<section class="panel"><div class="section-head">'
        f"<div><h2>{escape(title)}</h2>{description}</div></div>{content}</section>"
    )


def console_metric(
    label: str,
    value: str,
    good: bool,
    *,
    href: str | None = None,
) -> str:
    body = (
        f'<span class="metric-label">{escape(label)}</span>'
        f"<strong>{escape(value)}</strong>"
        f'<span class="metric-health {"good" if good else "bad"}">'
        f'{"正常" if good else "注意"}</span>'
    )
    if href is None:
        return f'<article class="metric">{body}</article>'
    return f'<a class="metric" href="{escape(href, quote=True)}">{body}</a>'


def console_banner(*, notice: str | None = None, error: str | None = None) -> str:
    if error:
        return f'<div class="banner error">{escape(error)}</div>'
    if notice:
        return f'<div class="banner success">{escape(notice)}</div>'
    return ""


def console_table(
    values: Mapping[str, object],
    *,
    labels: Mapping[str, str] | None = None,
    url_fields: Mapping[str, str] | None = None,
) -> str:
    names = labels or {}
    urls = url_fields or {}
    rows: list[str] = []
    for key, raw in values.items():
        rendered = console_value(raw)
        if key in urls and isinstance(raw, str) and is_safe_outlook_url(raw):
            rendered = (
                f'<a href="{escape(raw, quote=True)}">{escape(urls[key])}</a>'
            )
        rows.append(
            f"<tr><th>{escape(names.get(key, key))}</th><td>{rendered}</td></tr>"
        )
    return '<div class="table-wrap"><table>' + "".join(rows) + "</table></div>"


def console_value(value: object) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return '<span class="muted">未提供</span>'
    if isinstance(value, datetime):
        return escape(value.isoformat())
    if isinstance(value, dict):
        return escape(", ".join(f"{key}={val}" for key, val in value.items()))
    return escape(str(value))


def is_safe_outlook_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.hostname in _OUTLOOK_HOSTS


_CONSOLE_CSS = """
:root{color-scheme:light;--ink:#10233f;--muted:#64748b;--line:#dce4ef;
--blue:#1769e0;--navy:#071a34;--green:#0f9f6e;--amber:#c56a08;--red:#c43d4b}
*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:var(--ink);
font-family:Inter,Segoe UI,Arial,sans-serif}a{color:var(--blue);text-decoration:none}
.topbar{background:var(--navy);color:#fff}.topbar-inner{max-width:1180px;margin:auto;
height:62px;padding:0 24px;display:flex;align-items:center;justify-content:space-between}
.brand{font-weight:750;letter-spacing:.01em}.nav{display:flex;gap:22px}.nav a{color:#c9d8eb}
.nav a.active{color:#fff;font-weight:750}
.shell{max-width:1180px;margin:0 auto;padding:30px 24px 56px}.hero{display:flex;
align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:24px}.eyebrow{
margin:0 0 8px;color:var(--blue);font-size:12px;font-weight:800;letter-spacing:.14em}
h1{font-size:38px;line-height:1.1;margin:0}.subtitle{color:var(--muted);margin:10px 0 0}
.state{display:inline-flex;align-items:center;gap:9px;padding:10px 14px;border-radius:99px;
background:#fff;border:1px solid var(--line);font-weight:700;white-space:nowrap}.dot,.indicator{
display:inline-block;width:10px;height:10px;border-radius:50%}.state.ok .dot,.indicator.on{
background:var(--green);box-shadow:0 0 0 4px #d9f5ea}.state.warn .dot,.indicator.off{
background:var(--amber);box-shadow:0 0 0 4px #fff0d6}.panel{background:#fff;border:1px solid
var(--line);border-radius:18px;padding:22px;margin-top:18px;box-shadow:0 6px 24px #18395d0a}
.section-head{display:flex;justify-content:space-between;margin-bottom:18px}.section-head h2{
font-size:20px;margin:0}.section-note{color:var(--muted);font-size:13px;margin:6px 0 0}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}.metric{
position:relative;display:flex;flex-direction:column;gap:7px;padding:16px;background:#f8fafc;
border:1px solid #edf1f6;border-radius:13px;color:var(--ink)}.metric-label{font-size:13px;
color:var(--muted)}.metric strong{font-size:21px}.metric-health{font-size:11px;font-weight:800;
text-transform:uppercase}.metric-health.good{color:var(--green)}.metric-health.bad{color:var(--amber)}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 8px;
border-top:1px solid #edf1f6;font-size:13px}th{width:35%;color:var(--muted);font-weight:600}
.switch-list{border-top:1px solid #edf1f6}.switch-row{display:flex;align-items:center;justify-content:
space-between;gap:20px;padding:17px 4px;border-bottom:1px solid #edf1f6}.switch-title{display:flex;
align-items:center;gap:10px}.switch-copy p{color:var(--muted);font-size:13px;margin:7px 0 0}.pill{
font-size:11px;font-weight:800;padding:4px 7px;border-radius:99px}.pill.enabled{color:#087a55;
background:#dff7ed}.pill.paused{color:#8c5714;background:#fff0d6}.unavailable{color:var(--red)}
.button{border:0;border-radius:9px;padding:10px 15px;font-weight:750;cursor:pointer;white-space:nowrap;
display:inline-block}.button.primary{background:var(--blue);color:#fff}.button.danger{background:#fff0f1;color:var(--red);
border:1px solid #ffd6da}.button.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
.button:disabled{opacity:.45;cursor:not-allowed}.action-grid{display:grid;
grid-template-columns:repeat(3,1fr);gap:14px}.action-card{min-height:230px;padding:18px;border:1px solid
var(--line);border-radius:14px;display:flex;flex-direction:column;justify-content:space-between}.action-card h3{
margin:12px 0 7px}.action-card p{color:var(--muted);font-size:13px;line-height:1.55}.action-card form{
display:flex;align-items:end;justify-content:space-between;gap:10px}.action-icon{display:grid;place-items:center;
width:38px;height:38px;border-radius:10px;background:#eaf2ff;color:var(--blue);font-size:22px;font-weight:800}
.limit{display:flex;flex-direction:column;color:var(--muted);font-size:11px;gap:4px}.limit input{
width:72px;padding:9px;border:1px solid var(--line);border-radius:8px}.two-col{display:grid;
grid-template-columns:repeat(2,1fr);gap:14px}.count-card{border:1px solid var(--line);border-radius:13px;
padding:16px}.count-card h3{margin:0 0 12px;font-size:15px}.count-card ul{list-style:none;margin:0;padding:0}
.count-card li{display:flex;justify-content:space-between;padding:7px 0;border-top:1px solid #edf1f6;
font-size:13px}.count-card a{display:block;padding:7px 0}.banner{padding:13px 16px;border-radius:11px;
margin-bottom:14px;font-weight:650}.banner.success{color:#087a55;background:#dff7ed}.banner.error{
color:#a62d3a;background:#fff0f1}.refreshing{color:var(--blue);display:flex;gap:9px;align-items:center}.spinner{
width:14px;height:14px;border:2px solid #b9d3f9;border-top-color:var(--blue);border-radius:50%}
.muted{color:var(--muted)}
.connection-row,.recipient-setting{display:flex;align-items:center;justify-content:space-between;gap:20px;
margin-top:18px;padding:16px;border:1px solid var(--line);border-radius:13px;background:#f8fafc}
.connection-row p,.recipient-setting small{display:block;color:var(--muted);font-size:13px;margin:6px 0 0}
.recipient-current{font-size:18px;font-weight:750;margin:7px 0}.recipient-setting form{display:flex;
align-items:end;gap:10px}.recipient-setting label{display:flex;flex-direction:column;gap:5px;color:var(--muted);
font-size:12px}.recipient-setting input[type=email]{min-width:280px;padding:10px;border:1px solid var(--line);
border-radius:8px;background:#fff;color:var(--ink)}.connection-row .button{display:inline-block}
.queue-list{display:flex;flex-direction:column;gap:12px}
.review-card,.brief-item{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;
padding:18px;border:1px solid var(--line);border-radius:14px;background:#f8fafc}
.review-card h3,.brief-item h3{margin:0 0 6px;font-size:18px}
.review-card p,.brief-item p{margin:0;color:var(--muted);font-size:13px;line-height:1.55}
.review-meta,.brief-meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.review-card .button,.brief-item .button{margin-top:2px}
.choice-list{display:flex;flex-direction:column;gap:8px;margin:16px 0}
.choice{display:flex;align-items:center;gap:10px;padding:12px 14px;border:1px solid var(--line);
border-radius:11px;background:#f8fafc;cursor:pointer;font-weight:650}
.choice:has(input:checked){border-color:#b9d3f9;background:#eaf2ff}
.decision-form .field{display:flex;flex-direction:column;gap:6px;margin:12px 0;color:var(--muted);font-size:12px}
.decision-form input[type=text]{padding:10px;border:1px solid var(--line);border-radius:8px;
max-width:360px;background:#fff;color:var(--ink);font-size:14px}
.decision-form .hint{color:var(--muted);font-size:13px;margin:0 0 12px}
.decision-form .question{font-size:15px;margin:0 0 4px}
.brief-links{display:flex;flex-wrap:wrap;gap:14px;margin-top:12px}
.empty{color:var(--muted);padding:36px 8px;text-align:center}
.diff-changed td{background:#fff8e8}
.crumb{display:flex;gap:10px;margin-bottom:8px;font-size:13px}
.crumb a{color:var(--muted)}
@media(max-width:820px){.metrics,.action-grid{grid-template-columns:1fr 1fr}.hero{flex-direction:column}
.nav{gap:12px}.switch-row,.connection-row,.recipient-setting,.review-card,.brief-item{align-items:flex-start}
.two-col{grid-template-columns:1fr}}
@media(max-width:560px){.shell{padding:22px 14px}.topbar-inner{padding:0 14px}.metrics,.action-grid{
grid-template-columns:1fr}.nav a:nth-child(3){display:none}h1{font-size:31px}.switch-row{flex-direction:column}
.switch-row form,.switch-row button,.connection-row .button,.review-card,.brief-item{width:100%}
.review-card,.brief-item{flex-direction:column}
.connection-row,.recipient-setting,.recipient-setting form{width:100%;flex-direction:column;align-items:stretch}
.recipient-setting input[type=email],.decision-form input[type=text]{min-width:0;width:100%;max-width:none}}
"""
