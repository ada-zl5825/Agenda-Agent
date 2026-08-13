# Recruitment Inbox Agent

面向个人求职流程的隐私优先邮件 Agent。当前仓库已完成技术设计中的 Phase 0、
Phase 1、Phase 2、Phase 3、Phase 3.5 与 Phase 4。

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

## Phase 2 已实现

- 使用 BeautifulSoup + lxml 将 HTML 确定性归一化为文本
- 删除 script、style、隐藏节点、图片/tracking pixel、无关 footer 与 quoted history
- 解析 126 自动转发和嵌套转发邮件，优先使用最内层原始招聘人、主题和正文
- 在 HTML 清理前发现 HTTP(S) 链接；原始链接仅存在于短生命周期敏感对象中
- 删除个人邮箱、电话号码、candidate ID、身份证/护照和学号模式
- 产生唯一允许跨越未来模型边界的 sanitized text
- 基于中英文主题、正文和发件域名的高召回招聘邮件 prefilter

## Phase 3 已实现

- 在 HTML 清理前提取并稳定编号动作链接
- 确定性分类 assessment、interview、meeting、confirmation、scheduling、
  application portal、offer 与 general 链接
- 模型可见文本仅包含链接类型、域名和 `ACTION_LINK_*` 不透明引用
- 使用带上下文绑定的 AES-256-GCM 加密原始 URL
- 通过异步 Azure Key Vault 客户端、托管身份和版本化密钥支持轮换
- PostgreSQL `secure_links` 表仅保存密文、nonce、密钥版本和经批准的安全元数据
- 相同邮件重复处理保持引用和数据库记录身份稳定

Phase 3 不包含 LLM、LangGraph、附件下载、日历或自动发信。数据库仍不保存原始邮件
正文、HTML、附件、明文 OAuth token 或明文动作 URL。

## Phase 3.5 已实现

- `Company`、`CompanyAlias` 与 `CompanyDomain` 规范实体和父子公司关系
- 公司名 Unicode/case/punctuation/whitespace 确定性规范化
- 按规范名称、别名、发件域名依次进行严格 exact match
- 未知公司保持 `UNRESOLVED`，冲突记录返回 `AMBIGUOUS`；不做模糊、向量或 LLM 匹配
- `Application` 用 `company_id` 表示规范身份，并原样保留 `raw_company_name`
- Phase 4 预留 `company_raw`、`role_raw` 原始抽取合同，不包含模型集成
- 可重复执行的 35 家常见招聘公司 seed 目录和 PostgreSQL 仓储

Seed 未覆盖且无法通过已审核域名命中的公司会保持 `UNRESOLVED`：系统保留原始公司名、
令 `company_id` 为空，也不会自动创建公司。目录后续补录后，需要显式重新运行 resolver；
不会静默回填历史记录。

## Phase 4 已实现

- 使用 LangChain `ChatOpenAI` / `AzureChatOpenAI` 与 Pydantic strict structured output 提取招聘语义证据
- 模型只接收脱敏正文、邮件接收时间和允许的 `ACTION_LINK_*` 引用
- 输出保留 `company_raw`、`role_raw`，不生成 `company_id`，与 Phase 3.5 公司解析分离
- 确定性校验处理链接幻觉、字段冲突、低置信度以及时间和时区歧义
- 未明确时区的时间不做推断，保留来源文本并进入 `NEEDS_REVIEW`
- 版本化 prompt 与九类 provider-independent 合同样例
- Azure OpenAI 使用 Function managed identity，无 API key；调用带超时和有界重试

Phase 4 是无状态语义提取层，不写数据库、不解析 canonical company、不创建日历或发送
邮件，也不新增 Alembic 迁移。数据库 head 仍为 Phase 3.5 的 `20260813_0004`。

## 本地启动

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 PostgreSQL。

```powershell
Copy-Item .env.example .env
uv sync --all-groups --locked
uv run alembic upgrade head
uv run seed-companies
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
- `AZURE_KEY_VAULT_URL`
- `LINK_ENCRYPTION_KEY_SECRET_NAME=recruitment-link-encryption-key`
- `KEY_VAULT_REQUEST_TIMEOUT_SECONDS=10`
- `LLM_ENABLED=true`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION=2024-10-21`（Foundry `/openai/v1` endpoint 会忽略此值）
- `AZURE_OPENAI_REQUEST_TIMEOUT_SECONDS=30`
- `AZURE_OPENAI_MAX_RETRY_ATTEMPTS=3`
- `MAIL_SYNC_SCHEDULE=0 */10 * * * *`
- `AzureWebJobsStorage__accountName`
- `AzureWebJobsStorage__credential=managedidentity`

部署前执行 `uv run alembic upgrade head`。Azure Functions 实例保持无状态；OAuth cache、
授权 flow、delta cursor 与动作链接均以密文或元数据形式保存在 PostgreSQL。

## 验证

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
```

Graph HTTP 契约使用 `respx` 测试；邮件夹具覆盖中文、英文和 126 嵌套转发场景；
privacy regression 验证 URL token、PII、隐藏内容和原始正文不会越过安全边界。
Docker 可用时可额外执行 PostgreSQL 集成测试：

```powershell
$env:RUN_POSTGRES_INTEGRATION="1"
uv run pytest -m integration
```

完整边界与后续 phase 见
[最终技术设计](docs/01_FINAL_TECHNICAL_DESIGN.md) 和 [AGENTS.md](AGENTS.md)。
