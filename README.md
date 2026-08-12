# Recruitment Inbox Agent

面向个人求职流程的隐私优先邮件 Agent。当前仓库已完成技术设计中的 Phase 0 和
Phase 1：Microsoft 委托授权、只读邮件访问、Inbox 增量同步和元数据持久化。

## Phase 1 已实现

- Microsoft OAuth 2.0 Authorization Code Flow（MSAL）
- 仅申请 `User.Read` 与 `Mail.Read`；不申请 `Mail.ReadWrite`
- AES-256-GCM 加密的持久化 MSAL token cache，带乐观并发版本
- 单次、限时、加密保存的 OAuth flow state
- 基于 `httpx` 和 Pydantic DTO 的 Microsoft Graph 客户端
- Inbox message delta、`nextLink` 分页与 `deltaLink` 持久化
- 401 后强制刷新一次 token
- 429 `Retry-After` 与 5xx/网络错误的有界重试
- PostgreSQL 邮件元数据幂等 upsert
- Azure Functions ASGI 入口和每 10 分钟一次的 Timer Trigger

Phase 1 不包含 LLM、邮件归一化、Action Link、附件下载、日历或自动发信。
数据库不保存原始邮件正文、HTML、附件或明文 OAuth token。

## 本地启动

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 PostgreSQL。

```powershell
Copy-Item .env.example .env
uv sync --all-groups --locked
uv run alembic upgrade head
uv run uvicorn recruitment_agent.api.app:app --reload
```

配置 `.env` 后，浏览器打开 `http://127.0.0.1:8000/auth/login` 完成 Microsoft 授权。
回调地址必须与 Entra App Registration 中登记的 Web redirect URI 完全一致。

生成 32 字节 token-cache 加密密钥的示例：

```powershell
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

该值属于生产密钥，不应提交到 Git；云端应通过 Function App 设置或 Key Vault 引用注入。

## Azure 配置

Azure Functions 部署会读取根目录的 `requirements.txt`。需要设置：

- `DATABASE_URL`
- `MICROSOFT_CLIENT_ID`
- `MICROSOFT_CLIENT_SECRET`
- `MICROSOFT_TENANT=consumers`
- `MICROSOFT_REDIRECT_URI`
- `MICROSOFT_CONNECTION_ID`
- `TOKEN_CACHE_ENCRYPTION_KEY`
- `TOKEN_CACHE_ENCRYPTION_KEY_VERSION=v1`
- `MAIL_SYNC_SCHEDULE=0 */10 * * * *`
- `AzureWebJobsStorage`
- `FUNCTIONS_WORKER_RUNTIME=python`

部署前执行 `uv run alembic upgrade head`。Azure Functions 实例保持无状态；OAuth cache、
授权 flow 与 delta cursor 均以密文或元数据形式保存在 PostgreSQL。

## 验证

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
```

Graph HTTP 契约使用 `respx` 测试。Docker 可用时可额外执行 PostgreSQL 集成测试：

```powershell
$env:RUN_POSTGRES_INTEGRATION="1"
uv run pytest -m integration
```

完整边界与后续 phase 见
[最终技术设计](docs/01_FINAL_TECHNICAL_DESIGN.md) 和 [AGENTS.md](AGENTS.md)。
