"""Privacy-safe, dependency-free HTML renderer for the Agent console."""

# Long lines are kept for the dependency-free inline CSS template.
# ruff: noqa: E501, RUF001

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from html import escape
from typing import ClassVar

from recruitment_agent.application.agent_console import (
    AgentConsoleSnapshot,
    AgentControlSwitch,
    AgentManualAction,
)
from recruitment_agent.application.operations import OperationStatus


class AgentDashboardRenderer:
    _NOTICES: ClassVar[dict[str, str]] = {
        "control-updated": "运行设置已更新。",
        "mailbox-connected": "Outlook 账号授权已更新；管理员登录身份没有改变。",
        "recipient-updated": "Daily Brief 收件地址已更新。",
    }
    _ERRORS: ClassVar[dict[str, str]] = {
        "OPERATION_CONFLICT": "设置已变化或依赖条件未满足，请刷新后重试。",
        "OPERATION_DISABLED": "该功能当前已暂停或尚未配置。",
        "CSRF_INVALID": "页面已过期，请刷新后重试。",
        "INVALID_REQUEST": "提交内容无效，请刷新后重试。",
        "INVALID_RECIPIENT": "收件地址无效，请输入完整的邮箱地址。",
    }

    def render(
        self,
        snapshot: AgentConsoleSnapshot,
        *,
        csrf_tokens: Mapping[str, str],
        operation_keys: Mapping[str, str],
        notice: str | None = None,
        error: str | None = None,
    ) -> str:
        ready = snapshot.readiness.ready
        auto_refresh = ""
        if (
            snapshot.selected_operation is not None
            and snapshot.selected_operation.status
            in {OperationStatus.QUEUED, OperationStatus.RUNNING}
        ):
            auto_refresh = '<meta http-equiv="refresh" content="3">'
        banner = self._banner(notice=notice, error=error)
        content = (
            '<header class="hero">'
            '<div><p class="eyebrow">RECRUITMENT INBOX AGENT</p>'
            '<h1>Agent 控制台</h1>'
            '<p class="subtitle">查看云端运行状态、控制自动化边界并触发幂等任务。</p></div>'
            f'<span class="state {"ok" if ready else "warn"}">'
            f'<span class="dot"></span>{"运行就绪" if ready else "需要处理"}</span>'
            "</header>"
            + banner
            + self._readiness(snapshot)
            + self._control_panel(snapshot, csrf_tokens)
            + self._daily_brief_settings(snapshot, csrf_tokens)
            + self._manual_actions(snapshot, csrf_tokens, operation_keys)
            + self._selected_operation(snapshot)
            + self._activity(snapshot)
        )
        return self._page("Agent 控制台", content, auto_refresh=auto_refresh)

    def _readiness(self, snapshot: AgentConsoleSnapshot) -> str:
        status = snapshot.status
        sync = status.mail_sync
        cards = (
            self._metric(
                "数据库",
                "已连接" if snapshot.readiness.database_ready else "不可用",
                snapshot.readiness.database_ready,
            )
            + self._metric(
                "Microsoft OAuth",
                "已授权" if snapshot.readiness.oauth_authorized else "需要登录",
                snapshot.readiness.oauth_authorized,
            )
            + self._metric(
                "邮件增量同步",
                "未运行" if sync.status is None else sync.status.value,
                sync.error_code is None,
            )
            + self._metric(
                "待 Review",
                str(status.open_review_count),
                status.open_review_count == 0,
                href="/reviews",
            )
        )
        details = self._table(
            {
                "同步游标": "已建立" if sync.cursor_present else "尚未建立",
                "上次同步开始 (UTC)": sync.last_started_at,
                "上次同步完成 (UTC)": sync.last_finished_at,
                "同步错误代码": sync.error_code,
                "最新 Daily Brief": status.latest_brief_date,
                "Daily Brief 状态": status.latest_brief_status,
            }
        )
        mailbox = (
            '<div class="connection-row"><div><strong>Agent Outlook 连接</strong>'
            '<p>控制台登录不会修改此授权；只有使用右侧操作才会连接或更换邮箱。</p></div>'
            '<a class="button primary" href="/auth/mailbox/connect">连接 / 更换 Outlook</a></div>'
        )
        return self._section(
            "运行概览",
            '<div class="metrics">' + cards + "</div>" + details + mailbox,
            "实时读取 PostgreSQL 状态；不展示邮件正文、邮件收发件人或 OAuth 凭证。",
        )

    def _control_panel(
        self,
        snapshot: AgentConsoleSnapshot,
        csrf_tokens: Mapping[str, str],
    ) -> str:
        control = snapshot.status.control
        capabilities = snapshot.status.capabilities
        rows = (
            self._switch(
                switch=AgentControlSwitch.MAIL_SYNC,
                title="邮件同步",
                description="定时从 Outlook Inbox 执行 delta 同步。",
                enabled=control.mail_sync_enabled,
                available=snapshot.readiness.oauth_authorized,
                version=control.version,
                csrf_tokens=csrf_tokens,
            )
            + self._switch(
                switch=AgentControlSwitch.WORKFLOW,
                title="招聘工作流",
                description="处理待分类邮件并运行确定性的 LangGraph 流程。",
                enabled=control.workflow_enabled,
                available=capabilities.workflow_processing_available,
                version=control.version,
                csrf_tokens=csrf_tokens,
            )
            + self._switch(
                switch=AgentControlSwitch.CALENDAR,
                title="Calendar 写入",
                description="为已验证的面试与截止时间创建或更新日历。",
                enabled=control.calendar_write_enabled,
                available=capabilities.calendar_write_available,
                version=control.version,
                csrf_tokens=csrf_tokens,
            )
            + self._switch(
                switch=AgentControlSwitch.DAILY_BRIEF,
                title="Daily Brief",
                description="按计划生成并发送每日招聘摘要。",
                enabled=control.daily_brief_enabled,
                available=capabilities.daily_brief_available,
                version=control.version,
                csrf_tokens=csrf_tokens,
            )
        )
        return self._section(
            "自动化开关",
            '<div class="switch-list">' + rows + "</div>",
            f"设置版本 {control.version} · 最近由 {escape(control.updated_by)} 更新",
        )

    def _daily_brief_settings(
        self,
        snapshot: AgentConsoleSnapshot,
        csrf_tokens: Mapping[str, str],
    ) -> str:
        control = snapshot.status.control
        recipient = control.daily_brief_recipient or ""
        current = (
            escape(control.daily_brief_recipient)
            if control.daily_brief_recipient is not None
            else '<span class="muted">尚未配置</span>'
        )
        form = (
            '<div class="recipient-setting"><div><span class="metric-label">当前收件地址</span>'
            f'<p class="recipient-current">{current}</p>'
            '<small>此地址仅在管理员登录后的页面显示，不进入操作日志。</small></div>'
            '<form method="post" action="/agent/settings/daily-brief-recipient">'
            '<label>新的收件地址<input type="email" name="recipient" required maxlength="254" '
            f'value="{escape(recipient, quote=True)}" autocomplete="email"></label>'
            f'<input type="hidden" name="expected_version" value="{control.version}">'
            '<input type="hidden" name="csrf_token" '
            f'value="{escape(csrf_tokens["settings:daily_brief_recipient"], quote=True)}">'
            '<button class="button primary" type="submit">保存收件地址</button></form></div>'
        )
        return self._section(
            "Daily Brief 收件设置",
            form,
            "修改后立即写入 PostgreSQL；无需重新部署 Azure 资源。",
        )

    def _switch(
        self,
        *,
        switch: AgentControlSwitch,
        title: str,
        description: str,
        enabled: bool,
        available: bool,
        version: int,
        csrf_tokens: Mapping[str, str],
    ) -> str:
        action = f"control:{switch.value}"
        target = not enabled
        unavailable = not available and target
        button = "暂停" if enabled else "开启"
        return (
            '<article class="switch-row">'
            '<div class="switch-copy">'
            f'<div class="switch-title"><span class="indicator {"on" if enabled else "off"}">'
            f'</span><strong>{escape(title)}</strong>'
            f'<span class="pill {"enabled" if enabled else "paused"}">'
            f'{"已开启" if enabled else "已暂停"}</span></div>'
            f'<p>{escape(description)}</p>'
            + ('<small class="unavailable">云端能力尚未配置</small>' if unavailable else "")
            + "</div>"
            f'<form method="post" action="/agent/control/{switch.value}">'
            f'<input type="hidden" name="enabled" value="{str(target).lower()}">'
            f'<input type="hidden" name="expected_version" value="{version}">'
            f'<input type="hidden" name="csrf_token" value="{escape(csrf_tokens[action], quote=True)}">'
            f'<button class="button {"danger" if enabled else "primary"}" type="submit"'
            f'{" disabled" if unavailable else ""}>{button}</button></form>'
            "</article>"
        )

    def _manual_actions(
        self,
        snapshot: AgentConsoleSnapshot,
        csrf_tokens: Mapping[str, str],
        operation_keys: Mapping[str, str],
    ) -> str:
        control = snapshot.status.control
        capabilities = snapshot.status.capabilities
        actions = (
            self._action_card(
                action=AgentManualAction.MAIL_SYNC,
                title="立即同步邮件",
                description="拉取 Outlook 的最新 delta；重复提交不会重复执行。",
                button="开始同步",
                enabled=control.mail_sync_enabled and snapshot.readiness.oauth_authorized,
                version=control.version,
                csrf_tokens=csrf_tokens,
                operation_keys=operation_keys,
            )
            + self._action_card(
                action=AgentManualAction.PROCESS_PENDING,
                title="处理待办邮件",
                description="把待处理邮件以子任务方式安全地送入工作流。",
                button="处理队列",
                enabled=(
                    control.workflow_enabled
                    and capabilities.workflow_processing_available
                ),
                version=control.version,
                csrf_tokens=csrf_tokens,
                operation_keys=operation_keys,
                batch=True,
            )
            + self._action_card(
                action=AgentManualAction.SEND_DAILY_BRIEF,
                title="发送今日 Daily Brief",
                description="立即生成今天的摘要并发送；同一天最多成功发送一次。",
                button="发送 Brief",
                enabled=(
                    control.daily_brief_enabled
                    and control.daily_brief_recipient is not None
                    and capabilities.daily_brief_available
                    and snapshot.readiness.oauth_authorized
                ),
                version=control.version,
                csrf_tokens=csrf_tokens,
                operation_keys=operation_keys,
            )
        )
        return self._section(
            "手动操作",
            '<div class="action-grid">' + actions + "</div>",
            '任务异步进入 Azure Queue；可在下方查看本次 operation 状态。',
        )

    def _action_card(
        self,
        *,
        action: AgentManualAction,
        title: str,
        description: str,
        button: str,
        enabled: bool,
        version: int,
        csrf_tokens: Mapping[str, str],
        operation_keys: Mapping[str, str],
        batch: bool = False,
    ) -> str:
        binding = f"operation:{action.value}"
        limit = (
            '<label class="limit">数量 <input type="number" name="batch_limit" '
            'value="25" min="1" max="100"></label>'
            if batch
            else ""
        )
        return (
            '<article class="action-card">'
            f'<div><span class="action-icon">{self._action_icon(action)}</span>'
            f'<h3>{escape(title)}</h3><p>{escape(description)}</p></div>'
            f'<form method="post" action="/agent/operations/{action.value}">'
            f'<input type="hidden" name="expected_version" value="{version}">'
            f'<input type="hidden" name="idempotency_key" '
            f'value="{escape(operation_keys[action.value], quote=True)}">'
            f'<input type="hidden" name="csrf_token" '
            f'value="{escape(csrf_tokens[binding], quote=True)}">'
            f'{limit}<button class="button primary" type="submit"'
            f'{"" if enabled else " disabled"}>{escape(button)}</button></form>'
            "</article>"
        )

    def _selected_operation(self, snapshot: AgentConsoleSnapshot) -> str:
        operation = snapshot.selected_operation
        if operation is None:
            return ""
        result = None
        if operation.result:
            result = ", ".join(
                f"{key}={value}" for key, value in sorted(operation.result.items())
            )
        details = self._table(
            {
                "operation_id": operation.id,
                "类型": operation.operation_type.value,
                "状态": operation.status.value,
                "请求时间 (UTC)": operation.requested_at,
                "开始时间 (UTC)": operation.started_at,
                "完成时间 (UTC)": operation.finished_at,
                "尝试次数": operation.attempt_count,
                "结果": result,
                "错误代码": operation.error_code,
            }
        )
        waiting = (
            '<p class="refreshing"><span class="spinner"></span>任务执行中，页面会自动刷新。</p>'
            if operation.status in {OperationStatus.QUEUED, OperationStatus.RUNNING}
            else ""
        )
        return self._section("本次操作", waiting + details)

    def _activity(self, snapshot: AgentConsoleSnapshot) -> str:
        status = snapshot.status
        return self._section(
            "处理统计",
            '<div class="two-col">'
            + self._count_card("邮件状态", status.source_email_counts)
            + self._count_card("工作流状态", status.workflow_counts)
            + self._count_card("操作状态", status.operation_counts)
            + '<article class="count-card"><h3>快捷入口</h3>'
            '<a href="/reviews">Review 队列</a>'
            '<a href="/brief/today">预览今日 Brief</a></article></div>',
        )

    def _count_card(self, title: str, values: Mapping[str, int]) -> str:
        rows = "".join(
            f'<li><span>{escape(key)}</span><strong>{value}</strong></li>'
            for key, value in sorted(values.items())
        ) or "<li><span>暂无数据</span><strong>0</strong></li>"
        return f'<article class="count-card"><h3>{escape(title)}</h3><ul>{rows}</ul></article>'

    def _banner(self, *, notice: str | None, error: str | None) -> str:
        if error in self._ERRORS:
            return f'<div class="banner error">{escape(self._ERRORS[error])}</div>'
        if notice in self._NOTICES:
            return f'<div class="banner success">{escape(self._NOTICES[notice])}</div>'
        return ""

    @staticmethod
    def _metric(label: str, value: str, good: bool, *, href: str | None = None) -> str:
        body = (
            f'<span class="metric-label">{escape(label)}</span>'
            f'<strong>{escape(value)}</strong><span class="metric-health {"good" if good else "bad"}">'
            f'{"正常" if good else "注意"}</span>'
        )
        return (
            f'<a class="metric" href="{escape(href, quote=True)}">{body}</a>'
            if href
            else f'<article class="metric">{body}</article>'
        )

    @staticmethod
    def _table(values: Mapping[str, object]) -> str:
        rows = "".join(
            f"<tr><th>{escape(key)}</th><td>{AgentDashboardRenderer._value(value)}</td></tr>"
            for key, value in values.items()
        )
        return '<div class="table-wrap"><table>' + rows + "</table></div>"

    @staticmethod
    def _value(value: object) -> str:
        if value is None or value == "" or value == {}:
            return '<span class="muted">未提供</span>'
        if isinstance(value, datetime):
            return escape(value.isoformat())
        return escape(str(value))

    @staticmethod
    def _section(title: str, content: str, subtitle: str | None = None) -> str:
        description = "" if subtitle is None else f"<p class=\"section-note\">{escape(subtitle)}</p>"
        return (
            '<section class="panel"><div class="section-head">'
            f"<div><h2>{escape(title)}</h2>{description}</div></div>{content}</section>"
        )

    @staticmethod
    def _action_icon(action: AgentManualAction) -> str:
        return {
            AgentManualAction.MAIL_SYNC: "↻",
            AgentManualAction.PROCESS_PENDING: "▶",
            AgentManualAction.SEND_DAILY_BRIEF: "✉",
        }[action]

    @staticmethod
    def _page(title: str, content: str, *, auto_refresh: str = "") -> str:
        return (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"{auto_refresh}<title>{escape(title)}</title>"
            "<style>"
            ":root{color-scheme:light;--ink:#10233f;--muted:#64748b;--line:#dce4ef;"
            "--blue:#1769e0;--navy:#071a34;--green:#0f9f6e;--amber:#c56a08;--red:#c43d4b}"
            "*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:var(--ink);"
            "font-family:Inter,Segoe UI,Arial,sans-serif}a{color:var(--blue);text-decoration:none}"
            ".topbar{background:var(--navy);color:#fff}.topbar-inner{max-width:1180px;margin:auto;"
            "height:62px;padding:0 24px;display:flex;align-items:center;justify-content:space-between}"
            ".brand{font-weight:750;letter-spacing:.01em}.nav{display:flex;gap:22px}.nav a{color:#c9d8eb}"
            ".shell{max-width:1180px;margin:0 auto;padding:30px 24px 56px}.hero{display:flex;"
            "align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:24px}.eyebrow{"
            "margin:0 0 8px;color:var(--blue);font-size:12px;font-weight:800;letter-spacing:.14em}"
            "h1{font-size:38px;line-height:1.1;margin:0}.subtitle{color:var(--muted);margin:10px 0 0}"
            ".state{display:inline-flex;align-items:center;gap:9px;padding:10px 14px;border-radius:99px;"
            "background:#fff;border:1px solid var(--line);font-weight:700;white-space:nowrap}.dot,.indicator{"
            "display:inline-block;width:10px;height:10px;border-radius:50%}.state.ok .dot,.indicator.on{"
            "background:var(--green);box-shadow:0 0 0 4px #d9f5ea}.state.warn .dot,.indicator.off{"
            "background:var(--amber);box-shadow:0 0 0 4px #fff0d6}.panel{background:#fff;border:1px solid "
            "var(--line);border-radius:18px;padding:22px;margin-top:18px;box-shadow:0 6px 24px #18395d0a}"
            ".section-head{display:flex;justify-content:space-between;margin-bottom:18px}.section-head h2{"
            "font-size:20px;margin:0}.section-note{color:var(--muted);font-size:13px;margin:6px 0 0}"
            ".metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}.metric{"
            "position:relative;display:flex;flex-direction:column;gap:7px;padding:16px;background:#f8fafc;"
            "border:1px solid #edf1f6;border-radius:13px;color:var(--ink)}.metric-label{font-size:13px;"
            "color:var(--muted)}.metric strong{font-size:21px}.metric-health{font-size:11px;font-weight:800;"
            "text-transform:uppercase}.metric-health.good{color:var(--green)}.metric-health.bad{color:var(--amber)}"
            ".table-wrap{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 8px;"
            "border-top:1px solid #edf1f6;font-size:13px}th{width:35%;color:var(--muted);font-weight:600}"
            ".switch-list{border-top:1px solid #edf1f6}.switch-row{display:flex;align-items:center;justify-content:"
            "space-between;gap:20px;padding:17px 4px;border-bottom:1px solid #edf1f6}.switch-title{display:flex;"
            "align-items:center;gap:10px}.switch-copy p{color:var(--muted);font-size:13px;margin:7px 0 0}.pill{"
            "font-size:11px;font-weight:800;padding:4px 7px;border-radius:99px}.pill.enabled{color:#087a55;"
            "background:#dff7ed}.pill.paused{color:#8c5714;background:#fff0d6}.unavailable{color:var(--red)}"
            ".button{border:0;border-radius:9px;padding:10px 15px;font-weight:750;cursor:pointer;white-space:nowrap}"
            ".button.primary{background:var(--blue);color:#fff}.button.danger{background:#fff0f1;color:var(--red);"
            "border:1px solid #ffd6da}.button:disabled{opacity:.45;cursor:not-allowed}.action-grid{display:grid;"
            "grid-template-columns:repeat(3,1fr);gap:14px}.action-card{min-height:230px;padding:18px;border:1px solid "
            "var(--line);border-radius:14px;display:flex;flex-direction:column;justify-content:space-between}.action-card h3{"
            "margin:12px 0 7px}.action-card p{color:var(--muted);font-size:13px;line-height:1.55}.action-card form{"
            "display:flex;align-items:end;justify-content:space-between;gap:10px}.action-icon{display:grid;place-items:center;"
            "width:38px;height:38px;border-radius:10px;background:#eaf2ff;color:var(--blue);font-size:22px;font-weight:800}"
            ".limit{display:flex;flex-direction:column;color:var(--muted);font-size:11px;gap:4px}.limit input{"
            "width:72px;padding:9px;border:1px solid var(--line);border-radius:8px}.two-col{display:grid;"
            "grid-template-columns:repeat(2,1fr);gap:14px}.count-card{border:1px solid var(--line);border-radius:13px;"
            "padding:16px}.count-card h3{margin:0 0 12px;font-size:15px}.count-card ul{list-style:none;margin:0;padding:0}"
            ".count-card li{display:flex;justify-content:space-between;padding:7px 0;border-top:1px solid #edf1f6;"
            "font-size:13px}.count-card a{display:block;padding:7px 0}.banner{padding:13px 16px;border-radius:11px;"
            "margin-bottom:14px;font-weight:650}.banner.success{color:#087a55;background:#dff7ed}.banner.error{"
            "color:#a62d3a;background:#fff0f1}.refreshing{color:var(--blue);display:flex;gap:9px;align-items:center}.spinner{"
            "width:14px;height:14px;border:2px solid #b9d3f9;border-top-color:var(--blue);border-radius:50%}"
            ".muted{color:var(--muted)}"
            ".connection-row,.recipient-setting{display:flex;align-items:center;justify-content:space-between;gap:20px;"
            "margin-top:18px;padding:16px;border:1px solid var(--line);border-radius:13px;background:#f8fafc}"
            ".connection-row p,.recipient-setting small{display:block;color:var(--muted);font-size:13px;margin:6px 0 0}"
            ".recipient-current{font-size:18px;font-weight:750;margin:7px 0}.recipient-setting form{display:flex;"
            "align-items:end;gap:10px}.recipient-setting label{display:flex;flex-direction:column;gap:5px;color:var(--muted);"
            "font-size:12px}.recipient-setting input[type=email]{min-width:280px;padding:10px;border:1px solid var(--line);"
            "border-radius:8px;background:#fff;color:var(--ink)}.connection-row .button{display:inline-block}"
            "@media(max-width:820px){.metrics,.action-grid{grid-template-columns:1fr 1fr}.hero{flex-direction:column}"
            ".nav{gap:12px}.switch-row,.connection-row,.recipient-setting{align-items:flex-start}.two-col{grid-template-columns:1fr}}"
            "@media(max-width:560px){.shell{padding:22px 14px}.topbar-inner{padding:0 14px}.metrics,.action-grid{"
            "grid-template-columns:1fr}.nav a:nth-child(3){display:none}h1{font-size:31px}.switch-row{flex-direction:column}"
            ".switch-row form,.switch-row button,.connection-row .button{width:100%}.connection-row,.recipient-setting,"
            ".recipient-setting form{width:100%;flex-direction:column;align-items:stretch}.recipient-setting input[type=email]{"
            "min-width:0;width:100%}}"
            '</style></head><body><nav class="topbar"><div class="topbar-inner">'
            '<a class="brand" href="/agent" style="color:white">Agenda Agent</a><div class="nav">'
            '<a href="/agent">控制台</a><a href="/reviews">Reviews</a>'
            '<a href="/brief/today">今日 Brief</a></div></div></nav>'
            f'<main class="shell">{content}</main></body></html>'
        )
