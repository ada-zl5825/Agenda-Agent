# Recruitment Inbox Agent

一个面向个人校招流程的招聘邮件工作流 Agent。系统以确定性工作流为主，LLM 仅承担经过隐私处理后的语义抽取，所有数据库、日历和邮件副作用都由应用层校验后执行。

当前仓库只完成技术设计中的 **Phase 0 — Foundation**：

- Python 3.12+ 与 `uv`
- `src` 分层布局与严格类型检查
- FastAPI / Azure Functions 的无业务逻辑入口
- 纯 Python 领域实体、外部端口与仓储接口
- PostgreSQL、SQLAlchemy 2 与 Alembic 基础设施
- pytest、Ruff、mypy、pre-commit 与 GitHub Actions
- 仓库级 Codex skills

Microsoft Graph、邮件正文处理、Action Link 加密、Azure OpenAI、LangGraph、Calendar 与 Daily Brief 均不在 Phase 0 范围内。

## 本地开发

要求：Python 3.12+、[uv](https://docs.astral.sh/uv/)。

```powershell
Copy-Item .env.example .env
uv sync --all-groups --locked
uv run alembic upgrade head
uv run uvicorn recruitment_agent.api.app:app --reload
```

默认健康检查：`GET http://127.0.0.1:8000/health`。

## 质量门禁

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
```

## 架构边界

依赖方向固定为：`Infrastructure -> Application -> Domain`。领域层不得导入 SQLAlchemy、Azure SDK、LangChain 或 LangGraph。PostgreSQL 是未来业务状态的 source of truth；邮件只是 evidence。

详细约束见 [最终技术设计](docs/01_FINAL_TECHNICAL_DESIGN.md) 和 [AGENTS.md](AGENTS.md)。
