# Recruitment Inbox Agent

面向个人求职流程的隐私优先邮件 Agent。当前仓库已完成技术设计中的 Phase 0、
Phase 1、Phase 2、Phase 3、Phase 3.5、Phase 4、Phase 4.5、Phase 5、Phase 6、
Phase 7、Phase 8 与 Phase 9A。

## Phase 1 已实现

- Microsoft OAuth 2.0 Authorization Code Flow（MSAL）
- 当前 delegated scopes 为 `User.Read`、`Mail.Read`、`Calendars.ReadWrite` 与 `Mail.Send`；
  始终不申请 `Mail.ReadWrite`
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
邮件。Phase 4 本身不新增 Alembic 迁移。

## Phase 4.5 已实现

- 将 Phase 4 的 `company_raw`、`role_raw` 直接接入确定性实体解析，不再调用 LLM 判断公司
- 公司规范名、别名与发件域名均使用 exact match，并保留匹配值与置信度
- 名称证据与域名证据指向不同公司时返回 `AMBIGUOUS`，未知公司返回 `UNRESOLVED`
- 轻量 `RoleNormalizer` 保留原始职位名，并生成规范名与辅助 `role_family`
- 以稳定 ID 幂等保存解析尝试；冲突候选单独持久化，支持后续 Review 审计
- `INVALID` 提取结果不会进入解析；`NEEDS_REVIEW` 只记录确定性证据，不授权业务变更

Phase 4.5 不匹配 Application、不引入 LangGraph、不创建日历、不发信，也不使用模糊匹配、
向量搜索、外部搜索或 LLM 公司规范化。

## Phase 5 已实现

- 显式 `StateGraph` 节点与确定性路由覆盖邮件准备、提取、校验、Review 和最终处理
- PostgreSQL `agent_checkpoint` schema 保存 durable checkpoint，稳定 run ID 同时作为 thread ID
- `processing_runs`、`llm_extractions` 与 `review_items` 保存幂等执行和人工审核审计
- 时区歧义、Application 歧义和日期时间冲突通过 `interrupt()` 暂停，并用 typed decision 恢复
- checkpoint 只包含脱敏文本、opaque link ref、结构化证据和数据库 ID
- 生产组合入口连接 Graph、Key Vault、Azure 模型与 PostgreSQL，并正确释放异步资源
- Phase 5 的原始边界用 typed no-op 隔离当时尚未实现的领域与 Calendar 副作用

Phase 5 不实现 Review 图形页面、Daily Brief、Application/Event 状态机或 Calendar 写入。
数据库 head 为 `20260813_0006`。

## 本地启动

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 PostgreSQL。

```powershell
Copy-Item .env.example .env
uv sync --all-groups --locked
uv run alembic upgrade head
uv run seed-companies
uv run uvicorn recruitment_agent.api.app:app --reload
```

配置 `.env` 并执行迁移后，浏览器打开 `http://127.0.0.1:8000/auth/login` 完成管理员登录，
再从控制台点击“连接 / 更换 Outlook”建立 Agent 的 Graph 授权。管理员登录不会覆盖邮箱
Token Cache；只有显式 Outlook 连接流程会更新它。
回调地址必须与 Entra App Registration 中登记的 Web redirect URI 完全一致。

生成 32 字节 token-cache 加密密钥的示例：

```powershell
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

该值属于生产密钥，不应提交到 Git；云端应通过 Function App 设置或 Key Vault 引用注入。

## Azure 配置

Azure Functions 部署会读取根目录的 `requirements.txt`。生成该文件时必须使用非 editable
项目安装，确保远程构建把 `recruitment_agent` 安装到运行时的 `site-packages`：

```powershell
uv --cache-dir .uv-cache export --format requirements-txt --no-dev --no-hashes --no-editable --frozen --output-file requirements.txt
```

需要设置：

- `DATABASE_URL`
- `MICROSOFT_CLIENT_ID`
- `MICROSOFT_CLIENT_SECRET`
- `MICROSOFT_TENANT=consumers`
- `MICROSOFT_REDIRECT_URI`
- `MICROSOFT_CONNECTION_ID`
- `ADMIN_MICROSOFT_HOME_ACCOUNT_ID`（可选恢复/首次部署 allowlist；现有部署由迁移从当前授权播种）
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
- `DAILY_BRIEF_ENABLED=false`（完成迁移和重新授权后再设为 `true`）
- `DAILY_BRIEF_RECIPIENT`（可选首次初始化值；之后由控制台数据库设置接管）
- `DAILY_BRIEF_SCHEDULE=0 0 * * * *`（UTC 每小时唤醒）
- `DAILY_BRIEF_LOCAL_HOUR=8`（按 `USER_TIMEZONE` 过滤，自动适配 DST）
- `PUBLIC_APP_BASE_URL`
- `WEB_SESSION_SIGNING_KEY`（独立 Base64 32 字节密钥，不得复用 token-cache key）
- `WEB_SESSION_TTL_SECONDS=28800`
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

## Phase 6 implemented

- Deterministic application resolution uses canonical company IDs, normalized roles, source-email
  links, and explicit Review decisions for ambiguous candidates.
- Semantic fingerprints and action idempotency keys prevent duplicate applications, events, and
  action items across retries.
- Assessment, interview, offer, and rejection evidence drives validated Application transitions
  with append-only status history.
- Interview reschedules update the resolved active event in place and preserve the previous values
  in event history; uncertain targets interrupt for Review.
- Domain writes are revalidated and applied atomically in PostgreSQL. Required unresolved time
  evidence yields a zero-mutation plan.
- Secure destinations remain encrypted; Phase 6 stores only the matching `secure_link_id` and keeps
  opaque refs in graph checkpoints.
- Alembic head for Phase 6 is `20260813_0007`; Phase 7 extends it with `20260813_0008`.

## Phase 7 implemented

- Provider-neutral Calendar planning accepts only resolved applications and active, timezone-aware
  interview or assessment/deadline events.
- Microsoft Graph creates private attendee-free events and updates the same immutable event on
  reschedule. Stable `transactionId` values and `calendar_links` prevent retry duplicates.
- Calendar descriptions contain only approved metadata, label durations as placeholders, and never
  contain decrypted action links or secret query strings.
- Missing or unsafe linked events enter `UNSAFE_CALENDAR_UPDATE` human Review instead of being
  recreated silently.
- Apply Alembic head `20260813_0008`, grant delegated `Calendars.ReadWrite`, reauthorize the account,
  then set `CALENDAR_SYNC_ENABLED=true`. It remains false by default.
- Phase 8 在此基础上提供 Daily Brief、`Mail.Send` 和图形化 Review；Calendar 边界保持不变。

## Phase 8 implemented

- 确定性 Daily Brief 查询和渲染覆盖 `TODAY`、`NEXT 48 HOURS`、Assessment、Interview、
  Action Required、New Updates、Waiting for Result 与 Needs Review；整个过程不调用 LLM。
- 每个 Needs Review 项只使用绝对路径 `/reviews/{review_id}` 深链，主操作固定为
  `Open Review`；URL 不携带决策、候选项或敏感查询参数。
- 图形化 Review 队列和详情页由短期 HMAC 会话保护；详情展示来源元数据、Application、
  提取与时间证据、校验发现、现值/拟议值、候选匹配、安全链接元数据、副作用预览、
  决策表单和审计结果。
- Review GET 无副作用；POST 使用与 session、review ID、version 绑定的 CSRF，并在服务端
  校验允许选项、typed override 和乐观并发后才恢复 LangGraph。
- 普通 ActionItem 链接只在最终 Brief 渲染边界解密；Review 页面从不解密。含明文链接的
  HTML 不持久化，数据库 `daily_briefs` 只保存每日发送状态和安全错误码。
- Graph `POST /me/sendMail` 只发送生成的 Brief，无附件、原始邮件正文或 HTML；同一天只
  认领一次，传输/5xx 结果不确定时标记 `uncertain` 且不自动重发。
- Azure Timer 每小时 UTC 唤醒，并只在 `USER_TIMEZONE` 的本地 08 点发送，以适配 Flex
  Consumption 不支持 Timer 时区设置的限制；迁移 head 为 `20260813_0009`，功能默认关闭。

## Phase 9A implemented

- `/agent` 提供登录后的图形化运行控制台，根路径会跳转到该页面。
- 页面显示数据库/OAuth readiness、四个 PostgreSQL 运行时开关、能力上限、同步时间与游标、
  安全错误码、聚合处理计数、Review 数量、Brief 状态和单次 operation 进度。
- 页面可开启/暂停邮件同步、工作流、Calendar 写入和 Daily Brief，并可异步触发邮件同步、
  bounded pending processing 与今日 Daily Brief 发送。
- 管理员登录与 Agent Outlook 授权已拆分；普通 `/auth/login` 不修改 Graph Token Cache，只有
  登录管理员主动点击“连接 / 更换 Outlook”才会更换邮箱授权，账号变化时旧 delta 游标会清空。
- Daily Brief 当前收件地址可在认证后的控制台显示和修改；环境变量只作为数据库首次初始化值，
  后续修改无需重新部署。地址不进入操作日志或公开 API。
- 浏览器只使用签名 session 与 action-bound CSRF；`OPS_API_TOKEN`、OAuth token、邮件正文和
  解密链接不会进入 HTML。
- 手动任务继续写入 `operation_runs` 并只向 Azure Queue 发送 opaque UUID；Daily Brief 保持
  每账户每天最多一次成功发送。迁移 head 为 `20260814_0011`。

完整边界与后续 phase 见
[最终技术设计](docs/01_FINAL_TECHNICAL_DESIGN.md) 和 [AGENTS.md](AGENTS.md)。
