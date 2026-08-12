# Recruitment Inbox Agent

**Final Technical Design v2.0**
**Target:** Personal Recruitment Workflow Agent
**Primary stack:** Microsoft Graph + Azure Functions + LangGraph + LangChain + Azure OpenAI + PostgreSQL

---

# 1. 项目定义

Recruitment Inbox Agent 是一个用于自动管理校招流程的个人 Agent。

邮件来源：

```text
126 校招邮箱
      │
      │ Auto Forward
      ▼
Dedicated Outlook
      │
      ▼
Microsoft Graph
      │
      ▼
Recruitment Inbox Agent
```

Agent 自动完成：

- 发现新的招聘邮件
- 判断邮件是否与招聘相关
- 提取公司、岗位、流程状态
- 识别笔试 / 测评
- 识别面试
- 识别截止日期
- 识别面试改期
- 识别需要确认的事项
- 识别 Offer / Reject / Result
- 维护 Application 状态
- 自动维护 Outlook Calendar
- 每日生成 Recruitment Brief
- 在提醒中保留测评 / 面试 / 确认等原始操作链接
- 对无法安全判断的事项要求人工确认

项目不是：

```text
LLM 自动操作一切
```

而是：

```text
Deterministic Workflow
        +
LLM Semantic Understanding
        +
Human Review
```

---

# 2. 核心设计原则

整个系统必须遵守以下边界。

## 2.1 LLM 只负责理解

LLM 可以回答：

```text
这是什么公司？
这是什么岗位？
这是面试还是测评？
时间是什么？
是否需要用户完成某件事情？
邮件是否在修改之前的安排？
```

LLM 不可以直接决定：

```text
INSERT database
UPDATE database
CREATE calendar
UPDATE calendar
DELETE calendar
SEND email
```

这些操作必须由 deterministic application layer 完成。

---

## 2.2 Email 是 Evidence，不是 Domain State

邮件只是事件来源：

```text
Email
  ↓
Evidence
  ↓
Application State Machine
```

真正的核心对象是：

```text
Application
RecruitmentEvent
ActionItem
```

而不是 Email。

---

## 2.3 所有副作用必须幂等

下面这些操作全部必须支持重复执行：

```text
mail sync
email processing
state transition
calendar create
calendar update
daily brief generation
```

同一封邮件执行两遍：

```text
不得产生两个面试
不得产生两个 Todo
不得产生两个 Calendar Event
```

---

## 2.4 时间不允许猜

例如：

```text
8 月 20 日下午 3 点面试
```

如果邮件没有明确 timezone：

```text
不得自动假设北京时间
```

必须进入：

```text
NEEDS_REVIEW
```

只有：

```text
北京时间 8 月 20 日下午 3 点
```

才可以安全 normalization。

---

## 2.5 Secret-bearing URL 不进入 LLM

原邮件：

```text
https://assessment.example.com/start?
candidate=123456
&token=abcdef
```

不得发送给云端模型。

模型看到：

```text
[ACTION_LINK_01: assessment link]
```

系统自己维护：

```text
ACTION_LINK_01
        ↕
encrypted original URL
```

---

# 3. 最终技术架构

```text
                         ┌──────────────────┐
                         │       126        │
                         │ Recruitment Mail │
                         └────────┬─────────┘
                                  │
                             Auto Forward
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Dedicated Outlook│
                         └────────┬─────────┘
                                  │
                           Microsoft Graph
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │     Mail Sync Job      │
                     │ Azure Function Timer   │
                     └───────────┬────────────┘
                                 │
                           Delta Query
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │      PostgreSQL       │
                     │    Source Emails      │
                     └──────────┬────────────┘
                                │
                                ▼
                   ┌──────────────────────────┐
                   │        LangGraph         │
                   │ Recruitment Mail Graph  │
                   └────────────┬─────────────┘
                                │
         ┌──────────────────────┼─────────────────────┐
         │                      │                     │
         ▼                      ▼                     ▼
 Email Normalizer       Secure Link Pipeline    Privacy Sanitizer
         │                      │                     │
         │                      │                     ▼
         │                      │              Sanitized Content
         │                      │                     │
         │                      │                     ▼
         │                      │                LangChain
         │                      │                     │
         │                      │                     ▼
         │                      │               Azure OpenAI
         │                      │                     │
         └──────────────────────┼─────────────────────┘
                                │
                                ▼
                         Structured Output
                                │
                                ▼
                       Deterministic Validator
                                │
                   ┌────────────┴────────────┐
                   │                         │
                 valid                   ambiguous
                   │                         │
                   ▼                         ▼
          Entity Resolution          LangGraph Interrupt
                   │                         │
                   ▼                         ▼
            State Machine             NEEDS_REVIEW
                   │
                   ▼
                Database
                   │
           ┌───────┴───────┐
           │               │
           ▼               ▼
      Action Items    Calendar Sync
                           │
                           ▼
                   Microsoft Graph
                           │
                           ▼
                    Outlook Calendar


                     Daily Brief Job
                           │
                           ▼
                Resolve encrypted links
                           │
                           ▼
                     Daily Brief
                           │
                           ▼
                    Outlook / API
```

LangGraph 官方将 workflow 定义为预先确定路径的执行过程，而 agent 更偏向模型动态决定工具与执行路径；本项目主流程明显属于前者，因此核心采用 LangGraph workflow，而不是无限循环式 Agent。

---

# 4. 最终技术栈

## Language

```text
Python 3.12+
```

## Dependency management

```text
uv
pyproject.toml
uv.lock
```

生产环境不使用 floating dependencies。

---

## Application API

```text
FastAPI
```

用于：

```text
/auth/login
/auth/callback

/brief/today

/reviews
/reviews/{id}

/health
```

Azure Functions 支持通过 ASGI middleware 承载 FastAPI，因此不需要额外维护传统常驻服务器。

---

## Serverless runtime

```text
Azure Functions
```

负责：

```text
HTTP API
Mail Sync Timer
Daily Brief Timer
future Graph Webhook
maintenance jobs
```

Azure Functions Timer Trigger 原生支持 scheduled function execution。

---

## Workflow orchestration

```text
LangGraph
```

具体：

```python
StateGraph
```

而不是：

```text
generic autonomous agent loop
```

LangGraph Graph API 使用显式 state、nodes 和 edges 构建 workflow。

---

## LLM integration

```text
LangChain
langchain-openai
```

用途仅限：

```text
model abstraction
structured output
prompt composition
model invocation
```

LangChain 当前支持 Azure OpenAI / Microsoft Foundry 模型以及 structured output。

---

## Model

```text
Azure OpenAI
```

具体 deployment 名称由环境变量配置：

```text
AZURE_OPENAI_DEPLOYMENT
```

不得 hardcode model 名。

---

## Structured schema

```text
Pydantic v2
```

Azure OpenAI Structured Outputs 可以让模型输出遵循指定 JSON Schema，比自由文本解析更适合信息抽取。

---

## Database

```text
PostgreSQL
```

负责：

```text
domain state
mail metadata
links
actions
events
processing audit
LangGraph checkpoint
```

---

## ORM

```text
SQLAlchemy 2.x
Alembic
psycopg 3
```

---

## LangGraph persistence

```text
langgraph-checkpoint-postgres
```

官方 LangGraph 提供 PostgreSQL checkpointer，可用于保存 graph checkpoint，实现恢复、interrupt 和 durable execution。

---

## Microsoft integration

不在 MVP 使用大型 Graph SDK。

采用：

```text
MSAL
+
httpx
+
Microsoft Graph REST API
```

理由：

```text
接口数量少
boundary 更明确
mock 简单
retry 更透明
减少 SDK DTO 对 domain 的污染
```

---

## HTML processing

```text
BeautifulSoup4
lxml
```

---

## Cryptography

```text
cryptography
AES-GCM
```

用于 Action URL 加密。

Encryption key：

```text
Azure Key Vault
```

---

## Testing

```text
pytest
pytest-asyncio
respx
testcontainers
```

---

## Quality

```text
Ruff
mypy
pre-commit
```

---

## CI/CD

```text
GitHub Actions
Azure deployment
```

---

# 5. Microsoft Authentication

使用：

```text
OAuth 2.0 Authorization Code Flow
```

不要使用：

```text
username/password
```

Microsoft Identity authorization-code flow 支持用户授权应用访问 Microsoft Graph；`offline_access` 用于获取后台刷新所需的 refresh capability。

---

# 6. Microsoft Graph Permissions

最终权限：

```text
openid
profile
offline_access
User.Read

Mail.Read

Calendars.ReadWrite

Mail.Send
```

其中：

### Mail.Read

读取招聘邮箱。

个人 Microsoft account 支持 delegated `Mail.Read`。

### Calendars.ReadWrite

用于：

```text
创建面试
修改面试
创建 Deadline
修改 Deadline
```

### Mail.Send

仅用于：

```text
发送 Daily Brief
```

不申请：

```text
Mail.ReadWrite
```

因为 V1 不需要：

```text
移动邮件
删除邮件
标记邮件
修改邮件
```

---

# 7. Microsoft Token Storage

禁止：

```text
直接把 refresh_token 明文存数据库
```

推荐：

```text
MSAL Token Cache
      ↓
serialized
      ↓
application encryption
      ↓
PostgreSQL
```

Encryption master key：

```text
Azure Key Vault
```

Azure Function 本身：

```text
stateless
```

---

# 8. Email Synchronization

第一版采用：

```text
Timer Trigger
     +
Graph Delta Query
```

不直接从 Webhook 开始。

Graph delta query 可以获取资源自上次同步以来的变化，而不需要不断完整扫描邮箱。

---

# 9. Mail Sync Flow

```text
Timer
 ↓
load delta_link
 ↓
Graph delta
 ↓
pagination
 ↓
new / changed messages
 ↓
upsert SourceEmail
 ↓
store next delta_link
 ↓
enqueue/process email
```

---

# 10. Sync State

```python
class MailSyncState:
    account_id: UUID

    folder_id: str

    delta_link: str | None

    last_sync_started_at: datetime | None
    last_sync_finished_at: datetime | None

    status: SyncStatus
```

---

# 11. Webhook

Webhook 放到后续阶段。

最终 Production 可以：

```text
Graph Change Notification
          ↓
       Webhook
          ↓
       Delta Query
```

Microsoft Graph 支持 change notifications，也明确支持 change notifications 与 delta query 组合。

即使加入 webhook：

```text
Delta Sync 仍然保留
```

用于 reconciliation。

---

# 12. Email Processing Graph

最终 LangGraph：

```text
START
  │
  ▼
load_source_email
  │
  ▼
normalize_email
  │
  ▼
extract_action_links
  │
  ▼
prefilter_recruitment
  │
  ├──── irrelevant ───→ mark_ignored ──→ END
  │
  ▼
sanitize_content
  │
  ▼
extract_recruitment_data
  │
  ▼
validate_extraction
  │
  ├──── ambiguous ─────→ request_review
  │                          │
  │                      INTERRUPT
  │                          │
  │                      human input
  │                          │
  │                      RESUME
  │                          │
  └──────────────────────────┘
  │
  ▼
resolve_application
  │
  ▼
resolve_existing_event
  │
  ▼
plan_state_transition
  │
  ▼
persist_domain_changes
  │
  ▼
sync_calendar
  │
  ▼
finalize_processing
  │
  ▼
END
```

---

# 13. LangGraph State

```python
class RecruitmentGraphState(TypedDict):
    processing_run_id: str
    source_email_id: str

    normalized_email: NormalizedEmail | None

    link_refs: list[str]

    sanitized_text: str | None

    extraction: RecruitmentExtraction | None

    application_id: str | None
    event_id: str | None
    action_item_ids: list[str]

    validation_errors: list[str]

    needs_review: bool
    review_reason: str | None

    calendar_operation: CalendarOperation | None

    status: str
```

---

# 14. Critical LangGraph Privacy Rule

Graph state **禁止包含**：

```text
raw email HTML

OAuth access token

refresh token

decrypted assessment URL

full candidate token

passport / ID

raw attachment
```

因为 LangGraph checkpointer 会保存 graph state。

可以保存：

```text
sanitized text
link reference
database IDs
validated extraction
processing metadata
```

---

# 15. Human-in-the-loop

LangGraph `interrupt()` 用于：

```text
timezone ambiguous
application identity ambiguous
conflicting interview times
uncertain reschedule
unsafe calendar update
```

LangGraph interrupt 可以暂停 execution、保存 state，然后等待外部输入并继续执行。

例如：

```text
Email:

“面试安排在明天下午 3 点。”

              ↓

timezone unresolved

              ↓

interrupt

              ↓

ReviewItem

“请选择：
中国时间
英国时间
其他
忽略”
```

用户确认：

```text
China / Asia/Shanghai
```

然后：

```text
resume graph
↓
calendar sync
```

---

# 16. Email Normalizer

输入：

```text
Graph Message
```

输出：

```python
class NormalizedEmail(BaseModel):
    source_email_id: UUID

    graph_message_id: str
    internet_message_id: str | None

    subject: str

    sender_name: str | None
    sender_address: str | None
    sender_domain: str | None

    received_at: datetime

    body_text: str

    outlook_web_link: str | None

    has_attachments: bool
```

Graph message API 可以返回消息信息并允许应用使用相应 Mail permissions 获取邮件。

---

# 17. Forwarded 126 Mail Handling

必须专门测试：

```text
126
 ↓
Outlook forward
```

因为转发后：

```text
Graph sender
```

不一定等于：

```text
original recruiter
```

因此 normalizer 需要提取：

```text
outer sender
original forwarded sender
original subject
forwarded body
```

最终 domain 应优先根据：

```text
original recruiter context
```

而不是仅依赖 Graph `from`。

---

# 18. Secure Action Link Pipeline

这是 V2 的关键模块。

注意：

> 这里的 Secure 表示链接中的 secret 不泄露给 LLM / logs / plain database，不代表目标网站已经经过恶意网站安全认证。

---

# 19. Link Extraction Timing

必须：

```text
Raw HTML
   │
   ├────→ Link Extractor
   │
   └────→ Sanitizer
```

而不是：

```text
Raw HTML
 ↓
Sanitizer
 ↓
尝试找链接
```

否则 token 会丢失。

---

# 20. Link Types

```python
class ActionLinkType(str, Enum):
    ASSESSMENT = "assessment"

    INTERVIEW = "interview"

    MEETING = "meeting"

    CONFIRMATION = "confirmation"

    SCHEDULING = "scheduling"

    APPLICATION_PORTAL = "application_portal"

    OFFER = "offer"

    GENERAL = "general"
```

---

# 21. SecureLink Schema

```python
class SecureLink(BaseModel):
    id: UUID

    source_email_id: UUID

    ref: str

    link_type: ActionLinkType

    domain: str

    encrypted_url: bytes
    nonce: bytes
    encryption_key_version: str

    display_text: str | None

    created_at: datetime
```

例如：

```text
ACTION_LINK_01
```

映射：

```text
https://assessment.bytedance.example/start?token=xxx
```

---

# 22. URL Encryption

推荐：

```text
AES-256-GCM
```

Key：

```text
Azure Key Vault
```

数据库存：

```text
ciphertext
nonce
key_version
domain
link type
```

数据库不存：

```text
plaintext full URL
```

---

# 23. Link Sanitization

原文：

```text
请点击：

https://assessment.example.com/start?
token=abc
&candidate=123
```

模型输入：

```text
请点击：

[ACTION_LINK_01: assessment link,
 domain=assessment.example.com]
```

---

# 24. LLM Output

```json
{
  "action_required": true,
  "action_type": "assessment",
  "action_link_ref": "ACTION_LINK_01"
}
```

LLM 不知道：

```text
token
candidate
完整URL
```

---

# 25. Daily Brief Link Resolution

Daily Brief 生成：

```text
ActionItem
   ↓
action_link_ref
   ↓
SecureLinkRepository
   ↓
decrypt
   ↓
Daily Brief Renderer
```

最终提醒：

```text
字节跳动｜在线测评

截止：
8 月 16 日 23:59 CST

[开始测评]

[查看原始邮件]
```

---

# 26. Outlook Original Email Link

系统同时保存：

```text
outlook_web_link
```

因此每个 Action 可以包含：

```text
Open Action Link
Open Original Email
```

---

# 27. Privacy Sanitizer

必须独立模块：

```text
privacy/
```

不能把隐私保护完全依赖 Prompt。

---

# 28. Sanitizer 删除内容

包括：

```text
电话号码
个人邮箱
candidate ID
身份证模式
护照模式
学号
带 secret 的 URL
tracking pixel
script
style
隐藏 HTML
无关 footer
重复 quoted content
```

---

# 29. Attachments

MVP：

```text
禁止自动下载附件
禁止附件进入 LLM
```

仅保存：

```text
has_attachments = true
```

未来如需处理：

```text
简历
PDF interview instructions
```

单独设计 attachment sandbox。

---

# 30. Recruitment Prefilter

第一层不用大模型。

使用：

```text
subject keywords
sender domain heuristics
body keywords
forwarded sender
```

例如：

```text
面试
测评
笔试
校招
招聘
候选人
录用

interview
assessment
application
recruitment
candidate
offer
deadline
```

输出：

```python
LIKELY_RECRUITMENT
UNKNOWN
UNLIKELY
```

策略：

```text
LIKELY → LLM
UNKNOWN → LLM
UNLIKELY → END
```

因为 dedicated Outlook 本身已经是招聘聚合邮箱：

```text
Prefilter 应偏 recall
```

不要为了节省几次模型调用漏掉面试。

---

# 31. LLM Extraction Schema

```python
class RecruitmentExtraction(BaseModel):
    relevant: bool

    company: str | None
    role: str | None

    event_type: Literal[
        "application_received",
        "assessment",
        "interview",
        "interview_reschedule",
        "action_required",
        "deadline",
        "result",
        "offer",
        "rejection",
        "general_update",
        "unknown",
    ]

    interview_round: str | None

    action_required: bool
    action_text: str | None

    action_link_ref: str | None

    event_datetime: datetime | None
    deadline: datetime | None

    timezone_explicit: bool
    timezone_text: str | None

    source_datetime_text: str | None
    source_deadline_text: str | None

    meeting_platform: str | None
    location: str | None

    company_confidence: float
    event_confidence: float
    datetime_confidence: float
```

---

# 32. Structured Output

采用：

```text
LangChain
        ↓
Azure OpenAI
        ↓
Pydantic Structured Output
```

不要：

```text
LLM自由文本
↓
regex解析JSON
```

LangChain 官方支持 typed structured outputs，Azure OpenAI 也支持基于 JSON Schema 的 structured output。

---

# 33. Prompt Contract

System Prompt 必须包含：

```text
You extract factual recruitment workflow information.

Use only information supported by the email.

Never invent:
- company
- role
- stage
- interview round
- date
- time
- timezone
- deadline

If uncertain, return null.

Never infer timezone solely from company location.

Preserve exact date/time text from the source.

Action links are represented by opaque references such as
ACTION_LINK_01. Return only the reference.

Do not decide database mutations.

Do not decide calendar operations.

Do not generate user-facing advice.
```

---

# 34. Time Validation

例如：

```text
北京时间 8月20日下午3点
```

合法：

```text
Asia/Shanghai
```

---

如果：

```text
8月20日下午3点
```

则：

```text
timezone_explicit = false
```

进入：

```text
NEEDS_REVIEW
```

---

# 35. Relative Time

例如：

```text
请于明天下午 5 点前完成
```

LLM 输入应同时包含：

```text
email_received_at
```

用于日期解析。

但 timezone 仍必须独立确定。

---

# 36. Deterministic Extraction Validator

```python
class ExtractionValidator:
    def validate(
        self,
        extraction: RecruitmentExtraction,
        email: NormalizedEmail,
    ) -> ValidationResult: ...
```

验证：

```text
required fields
datetime validity
deadline validity
timezone
link ref existence
confidence thresholds
event consistency
```

---

# 37. Domain Aggregate

核心：

```text
Application
```

结构：

```text
Application
│
├── SourceEmails[]
│
├── RecruitmentEvents[]
│
├── ActionItems[]
│
└── StatusHistory[]
```

---

# 38. Application Status

```python
class ApplicationStatus(str, Enum):
    UNKNOWN = "unknown"

    APPLIED = "applied"

    ASSESSMENT_PENDING = "assessment_pending"
    ASSESSMENT_COMPLETED = "assessment_completed"

    INTERVIEW_PENDING = "interview_pending"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    INTERVIEW_COMPLETED = "interview_completed"

    OFFER = "offer"

    REJECTED = "rejected"

    WITHDRAWN = "withdrawn"
```

---

# 39. Recruitment Event

```python
class RecruitmentEvent:
    id: UUID

    application_id: UUID

    type: RecruitmentEventType

    round: str | None

    starts_at: datetime | None
    deadline_at: datetime | None

    timezone: str | None

    source_datetime_text: str | None

    status: EventStatus
```

---

# 40. Event Status

```text
ACTIVE

COMPLETED

SUPERSEDED

CANCELLED
```

---

# 41. ActionItem

```python
class ActionItem:
    id: UUID

    application_id: UUID

    source_email_id: UUID

    type: ActionType

    title: str

    due_at: datetime | None

    secure_link_id: UUID | None

    status: ActionStatus
```

Status：

```text
OPEN
DONE
SUPERSEDED
CANCELLED
```

---

# 42. Reschedule Algorithm

原邮件：

```text
Tencent Interview
20 Aug
15:00 CST
```

创建：

```text
RecruitmentEvent #100
CalendarEvent #ABC
```

新邮件：

```text
改至
21 Aug
16:00 CST
```

必须：

```text
resolve Application
 ↓
find matching active interview
 ↓
score candidate events
 ↓
resolve #100
 ↓
update #100
 ↓
preserve old value in history
 ↓
update CalendarEvent #ABC
```

不得：

```text
create RecruitmentEvent #101
```

---

# 43. Entity Resolution

Application matching 顺序：

```text
exact company + exact role

normalized company + normalized role

thread / source references

recent open application

semantic candidate match
```

如果有多个候选：

```text
NEEDS_REVIEW
```

LLM 不得擅自选一个。

---

# 44. Idempotency

三层。

## Mail identity

```text
graph_message_id UNIQUE
```

---

## Internet identity

```text
internet_message_id
```

建立 index。

---

## Semantic fingerprint

```text
SHA256(
normalized_company
+
normalized_role
+
event_type
+
normalized_datetime
+
deadline
)
```

---

# 45. PostgreSQL Schema

建议 schema：

```text
app.*
agent_checkpoint.*
```

LangGraph checkpoint 和 domain tables 逻辑隔离。

---

# 46. Tables

```text
users

microsoft_connections

mail_sync_states

source_emails

applications

application_status_history

recruitment_events

event_history

action_items

secure_links

calendar_links

processing_runs

llm_extractions

review_items

daily_briefs
```

---

# 47. source_emails

```text
id UUID PK

graph_message_id UNIQUE

internet_message_id

subject

sender_domain

received_at

outlook_web_link

body_hash

has_attachments

processing_status

application_id nullable

created_at
updated_at
```

不保存：

```text
raw_html
```

---

# 48. processing_runs

```text
id UUID

source_email_id UUID

graph_thread_id

current_stage

status

prompt_version

model_deployment

started_at
finished_at

error_code
error_detail_sanitized
```

---

# 49. review_items

```text
id

processing_run_id

reason

question

allowed_choices

status

resolution

created_at
resolved_at
```

---

# 50. calendar_links

```text
id

recruitment_event_id UNIQUE

provider

calendar_event_id

last_synced_at
```

保证：

```text
1 RecruitmentEvent
=
max 1 active Calendar Event
```

---

# 51. Calendar Creation Rules

自动创建 Calendar 必须满足：

```text
event confirmed

datetime present

timezone resolved

not duplicate

application resolved

validation passed
```

否则：

```text
NEEDS_REVIEW
```

---

# 52. Calendar Event

例如：

```text
Tencent | Backend Engineer | Interview 1
```

Description：

```text
Company: Tencent

Role:
Backend Engineer

Stage:
Interview 1

Original time:
北京时间 8月20日 15:00

Source:
Open original email

Managed by Recruitment Inbox Agent
```

不要写：

```text
assessment token
candidate token
sensitive URL query
```

---

# 53. Assessment Deadline Calendar

测评可以创建：

```text
ByteDance | Assessment Deadline
```

建议：

```text
30-minute placeholder at deadline
```

或：

```text
all-day / timed deadline event
```

由配置决定。

不要假装知道测评实际需要多长时间。

---

# 54. Daily Brief

默认 sections：

```text
TODAY

NEXT 48 HOURS

ASSESSMENTS

UPCOMING INTERVIEWS

ACTION REQUIRED

NEW UPDATES

WAITING FOR RESULT

NEEDS REVIEW
```

---

# 55. Daily Brief Example

```text
Recruitment Brief
13 August 2026


TODAY

Tencent
Backend Engineer
Interview 1

15:00 China
08:00 UK

Join interview
Open original email


NEXT 48 HOURS

ByteDance
Software Engineer
Online Assessment

Deadline:
16 Aug 23:59 China

Start assessment
Open original email


ACTION REQUIRED

Meituan
Backend Engineer

Confirm interview availability

Confirm
Open original email


NEEDS REVIEW

Huawei
Interview invitation

“8 月 20 日下午 3 点”

Timezone not specified.
Calendar event was NOT created.
```

---

# 56. Daily Brief Rendering Rule

Brief renderer：

```text
不得调用 LLM
```

第一版完全 deterministic。

原因：

```text
减少成本
减少幻觉
避免 LLM 改写时间
确保链接准确
```

---

# 57. Brief Delivery

使用：

```text
Microsoft Graph
Mail.Send
```

发送到用户配置的：

```text
DAILY_BRIEF_RECIPIENT
```

也提供：

```text
GET /brief/today
```

用于调试。

---

# 58. API

## Authentication

```text
GET /auth/login

GET /auth/callback
```

---

## Status

```text
GET /health

GET /status
```

---

## Brief

```text
GET /brief/today
```

---

## Reviews

```text
GET /reviews

GET /reviews/{review_id}

POST /reviews/{review_id}/resolve
```

---

## Development only

```text
POST /internal/sync

POST /internal/process/{email_id}
```

Production 禁止公开。

---

# 59. Error Codes

```text
AUTH_REQUIRED

GRAPH_AUTH_ERROR

GRAPH_RATE_LIMITED

GRAPH_FETCH_FAILED

DELTA_STATE_INVALID

EMAIL_NORMALIZATION_FAILED

PRIVACY_SANITIZATION_FAILED

LINK_EXTRACTION_FAILED

LINK_ENCRYPTION_FAILED

LLM_TIMEOUT

LLM_SCHEMA_INVALID

EXTRACTION_AMBIGUOUS

DATETIME_AMBIGUOUS

TIMEZONE_AMBIGUOUS

APPLICATION_AMBIGUOUS

DATABASE_ERROR

CALENDAR_CREATE_FAILED

CALENDAR_UPDATE_FAILED

BRIEF_SEND_FAILED
```

---

# 60. Retry Policy

Retryable：

```text
HTTP 429
temporary Graph failure
LLM timeout
Azure transient error
database transient connection
```

Non-retryable：

```text
invalid schema
ambiguous timezone
unknown application identity
invalid encrypted link
```

---

# 61. Observability

每个 processing run：

```text
trace_id
processing_run_id
source_email_id
```

日志可以记录：

```text
stage

latency

success/failure

model deployment

token usage

event type

application id
```

日志不得记录：

```text
email body

raw HTML

OAuth token

refresh token

plaintext action URL

candidate ID

phone number

private email
```

---

# 62. Data Retention

长期保存：

```text
structured recruitment state

subject

sender domain

received timestamp

email Graph ID

Outlook webLink

body hash

LLM structured result

audit history
```

不长期保存：

```text
raw email HTML

attachments

plaintext secret URLs
```

---

# 63. Repository Structure

```text
recruitment-inbox-agent/
│
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── host.json
├── function_app.py
│
├── docs/
│   ├── 01_FINAL_TECHNICAL_DESIGN.md
│   ├── 02_DOMAIN_MODEL.md
│   ├── 03_PRIVACY_MODEL.md
│   ├── 04_GRAPH_WORKFLOW.md
│   ├── 05_OPERATIONS.md
│   └── 06_TEST_PLAN.md
│
├── src/
│   └── recruitment_agent/
│       │
│       ├── api/
│       │   ├── app.py
│       │   ├── auth.py
│       │   ├── briefs.py
│       │   └── reviews.py
│       │
│       ├── config/
│       │   └── settings.py
│       │
│       ├── domain/
│       │   ├── application.py
│       │   ├── event.py
│       │   ├── action.py
│       │   ├── transitions.py
│       │   └── resolution.py
│       │
│       ├── graph/
│       │   ├── state.py
│       │   ├── builder.py
│       │   ├── routing.py
│       │   └── nodes/
│       │       ├── load_email.py
│       │       ├── normalize.py
│       │       ├── extract_links.py
│       │       ├── prefilter.py
│       │       ├── sanitize.py
│       │       ├── extract.py
│       │       ├── validate.py
│       │       ├── review.py
│       │       ├── resolve.py
│       │       ├── persist.py
│       │       └── calendar.py
│       │
│       ├── microsoft/
│       │   ├── auth.py
│       │   ├── graph_client.py
│       │   ├── mail.py
│       │   ├── delta.py
│       │   ├── calendar.py
│       │   └── send_mail.py
│       │
│       ├── email/
│       │   ├── normalizer.py
│       │   ├── forwarded_parser.py
│       │   └── prefilter.py
│       │
│       ├── privacy/
│       │   ├── sanitizer.py
│       │   ├── pii.py
│       │   └── url_redaction.py
│       │
│       ├── links/
│       │   ├── extractor.py
│       │   ├── classifier.py
│       │   ├── encryption.py
│       │   └── repository.py
│       │
│       ├── llm/
│       │   ├── model.py
│       │   ├── schema.py
│       │   ├── prompts.py
│       │   └── extractor.py
│       │
│       ├── calendar/
│       │   ├── service.py
│       │   └── planner.py
│       │
│       ├── briefs/
│       │   ├── query.py
│       │   ├── renderer.py
│       │   └── sender.py
│       │
│       ├── persistence/
│       │   ├── models.py
│       │   ├── repositories/
│       │   ├── session.py
│       │   └── migrations/
│       │
│       └── observability/
│           ├── logging.py
│           └── metrics.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── graph/
│   ├── contract/
│   ├── privacy/
│   ├── e2e/
│   └── fixtures/
│       └── emails/
│
└── .agents/
    └── skills/
        ├── recruitment-domain/
        ├── graph-mail-calendar/
        ├── langgraph-workflow/
        ├── structured-recruitment-extraction/
        ├── privacy-email-processing/
        ├── secure-action-links/
        └── azure-serverless-ops/
```

Codex 当前会从仓库中的 `.agents/skills` 发现 repo-scoped Skills；每个 Skill 至少包含带 `name`、`description` metadata 的 `SKILL.md`。

---

# 64. Environment Variables

```text
APP_ENV=

DATABASE_URL=

USER_TIMEZONE=

MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_TENANT=consumers
MICROSOFT_REDIRECT_URI=

AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_DEPLOYMENT=

AZURE_KEY_VAULT_URL=

LINK_ENCRYPTION_KEY_SECRET_NAME=

MAIL_FOLDER_ID=

MAIL_SYNC_ENABLED=true
MAIL_SYNC_INTERVAL_MINUTES=10

CALENDAR_AUTO_CREATE=true

DAILY_BRIEF_ENABLED=true
DAILY_BRIEF_RECIPIENT=
DAILY_BRIEF_TIME=

LLM_ENABLED=true
```

---

# 65. Packages

核心 dependencies：

```text
fastapi
pydantic
pydantic-settings

azure-functions
azure-identity
azure-keyvault-secrets

msal
httpx

langchain
langchain-openai
langgraph
langgraph-checkpoint-postgres

sqlalchemy
alembic
psycopg

beautifulsoup4
lxml

cryptography

structlog
```

Dev：

```text
pytest
pytest-asyncio
respx
testcontainers
ruff
mypy
pre-commit
```

---

# 66. Testing Strategy

## Unit

```text
normalizer
forward parser
PII sanitizer
URL sanitizer
link encryption
link classification
timezone validation
fingerprint
state transitions
reschedule resolver
brief renderer
```

---

# 67. Privacy Regression Tests

必须验证：

```text
raw URL token never reaches LLM mock

phone number never reaches LLM mock

OAuth token never enters logs

plaintext secure URL never enters logs

attachments are never downloaded
```

---

# 68. Graph Tests

LangGraph 官方推荐在测试中构造 graph 并使用独立 checkpointer，使 stateful workflow 可重复测试。

测试：

```text
happy path

irrelevant email

assessment

interview

ambiguous timezone interrupt

resume after review

duplicate email

reschedule

LLM error

database error

calendar retry
```

---

# 69. Contract Fixtures

至少：

```text
assessment_cn.html

assessment_en.html

interview_cn.html

interview_en.html

interview_no_timezone.html

interview_relative_time.html

reschedule_cn.html

reschedule_en.html

offer.html

rejection.html

action_required.html

forwarded_126.html

forwarded_nested.html

duplicate.html

non_recruitment.html

tokenized_assessment_link.html

meeting_link.html
```

---

# 70. E2E Acceptance Test 1

输入：

```text
字节跳动在线测评

请于北京时间
8 月 16 日 23:59 前完成测评。

[开始测评]
```

结果：

```text
1 Application

1 Assessment Event

1 ActionItem

1 encrypted SecureLink

1 Calendar deadline

Daily Brief contains:
Start Assessment

LLM input contains:
ACTION_LINK_01

LLM input DOES NOT contain:
token
```

---

# 71. E2E Acceptance Test 2

输入：

```text
腾讯后台开发工程师一面

北京时间：
8 月 20 日 15:00
```

结果：

```text
Application

INTERVIEW_SCHEDULED

1 RecruitmentEvent

1 CalendarEvent
```

---

# 72. E2E Acceptance Test 3

输入：

```text
原定面试调整至：

北京时间
8 月 21 日 16:00
```

结果：

```text
existing RecruitmentEvent updated

same CalendarEvent updated

0 duplicate events
```

---

# 73. E2E Acceptance Test 4

输入：

```text
面试安排：

8 月 21 日下午 3 点
```

结果：

```text
NEEDS_REVIEW

LangGraph interrupt

0 calendar writes
```

---

# 74. E2E Acceptance Test 5

同一 message 重跑 5 次。

结果：

```text
1 SourceEmail

1 Application event

1 ActionItem

1 Calendar Event
```

---

# 75. Project AGENTS.md

```markdown
# Recruitment Inbox Agent

Follow docs/01_FINAL_TECHNICAL_DESIGN.md.

## Architecture

Keep domain logic independent from:

- Microsoft Graph
- LangChain
- LangGraph
- Azure OpenAI
- Azure Functions
- PostgreSQL implementations

Use dependency inversion at external boundaries.

## LangGraph

LangGraph orchestrates workflow execution.

LangGraph state is not domain state.

PostgreSQL domain tables are the source of truth.

Do not place decrypted secret URLs, OAuth credentials,
raw email HTML, or attachments in graph state.

## LLM

LLMs perform semantic extraction only.

Never let an LLM directly mutate:

- database state
- calendars
- email
- secure links

All LLM outputs must use typed structured output.

All LLM outputs must pass deterministic validation.

## Time

Never silently infer timezone.

Ambiguous time must enter NEEDS_REVIEW.

## Privacy

Never log raw email body.

Never log OAuth tokens.

Never log plaintext secret-bearing URLs.

Never send attachments to the LLM.

Only sanitized email content may cross the model boundary.

## Links

Extract action links before sanitization.

Encrypt secret-bearing URLs before persistence.

The model receives opaque link references only.

## Data

All ingestion and mutations must be idempotent.

Use Alembic for every schema change.

Never edit production schema manually.

## Engineering

Use typed Python.

Use async I/O for external services.

External APIs must be behind typed interfaces.

No business logic in Azure Function entrypoints.

No business logic in FastAPI routes.

Routes and Functions invoke application services only.

## Testing

Every production bug requires a regression test.

Before completion run:

uv run ruff check .
uv run mypy src
uv run pytest

Do not claim completion unless all required checks pass.

## Scope

Do not implement future phases without explicit instruction.

Do not add Gmail, IMAP, browser automation,
automatic recruiter replies, or attachment ingestion
unless explicitly requested.
```

Codex 会在开始工作前发现并读取适用的 `AGENTS.md`，因此这里适合存放整个仓库长期有效的工程规则。

---

# 76. Required Codex Skills

Skills 放：

```text
.agents/skills/
```

每个 Skill 保持一个职责。OpenAI 当前建议 Skill 聚焦于可重复、明确的 workflow，而不是把整个项目塞进一个巨型 Skill。

---

# Skill 1 — recruitment-domain

```yaml
---
name: recruitment-domain
description: Use when implementing or changing recruitment applications, application status, assessments, interviews, deadlines, offers, rejections, event matching, duplicate handling, rescheduling, or state transitions.
---
```

Rules：

```text
Application is the aggregate root.

Email is evidence, not state.

LLM output never directly mutates domain state.

Transitions must be deterministic.

All mutations must be idempotent.

A reschedule should update an existing event when resolvable.

Ambiguous application resolution must produce NEEDS_REVIEW.

Preserve event history before destructive updates.
```

---

# Skill 2 — graph-mail-calendar

```yaml
---
name: graph-mail-calendar
description: Use when implementing Microsoft OAuth, Microsoft Graph mail retrieval, delta synchronization, Outlook message access, calendar creation or updates, Daily Brief sending, Graph retries, or Graph contract tests.
---
```

Rules：

```text
Use delegated permissions.

Prefer least privilege.

Mail reading uses Mail.Read.

Do not require Mail.ReadWrite for V1.

Calendar mutations use Calendars.ReadWrite.

Daily Brief sending uses Mail.Send.

Use delta query for incremental synchronization.

Never expose Graph DTOs to domain logic.

Never log access or refresh tokens.

Handle pagination and Retry-After.

Graph writes must be retry-safe.
```

---

# Skill 3 — langgraph-workflow

```yaml
---
name: langgraph-workflow
description: Use when implementing or changing the Recruitment Inbox LangGraph, graph state, nodes, routing, checkpoints, interrupts, human review, resume behavior, workflow retries, or graph tests.
---
```

Rules：

```text
Use StateGraph.

Workflow paths should be explicit.

Graph state represents execution state, not business state.

PostgreSQL domain data remains source of truth.

Never persist raw HTML in graph state.

Never persist decrypted secure links in graph state.

Use interrupt for genuine human decisions.

Every interrupted graph must be resumable.

Nodes should be small and deterministic where possible.

LLM invocation belongs in a dedicated extraction node.

Database and Calendar side effects must occur after validation.

Every graph branch requires a test.
```

---

# Skill 4 — structured-recruitment-extraction

```yaml
---
name: structured-recruitment-extraction
description: Use when modifying recruitment LLM prompts, LangChain model integration, Azure OpenAI calls, Pydantic extraction schemas, structured outputs, model validation, confidence handling, or extraction fixtures.
---
```

Rules：

```text
Use Structured Outputs.

Never parse prose output.

Schemas live in Python code.

Prompts must be versioned.

Never allow timezone invention.

Retain exact source datetime strings.

Return null when evidence is insufficient.

Opaque ACTION_LINK refs may be returned.

Original URLs may not be sent to the model.

All model outputs pass deterministic validation.

Schema changes require contract fixture updates.
```

---

# Skill 5 — privacy-email-processing

```yaml
---
name: privacy-email-processing
description: Use whenever email HTML, forwarded messages, PII, logging, storage, attachments, sanitization, model inputs, data retention, or privacy boundaries are changed.
---
```

Rules：

```text
Raw attachments never reach the model.

Raw HTML is not persisted by default.

Raw email body is never logged.

Tracking pixels must be removed.

Sensitive URL content must be replaced before inference.

Unnecessary phone numbers and email addresses must be redacted.

Only sanitized text may cross the LLM boundary.

Privacy regressions require dedicated tests.
```

---

# Skill 6 — secure-action-links

```yaml
---
name: secure-action-links
description: Use when extracting, classifying, encrypting, storing, resolving, rendering, or testing assessment links, interview links, confirmation links, meeting links, scheduling links, or other secret-bearing recruitment URLs.
---
```

Rules：

```text
Extract links before sanitization.

Only allow explicitly supported URL schemes.

Do not expose plaintext URLs to the LLM.

Do not log plaintext secure links.

Use opaque ACTION_LINK references.

Encrypt sensitive URLs before persistence.

Store domain separately for display and audit.

Calendar descriptions must not include secret tokens.

Brief renderer may decrypt links only immediately before rendering.

Never treat a stored link as inherently trustworthy merely because it was encrypted.
```

---

# Skill 7 — azure-serverless-ops

```yaml
---
name: azure-serverless-ops
description: Use when implementing Azure Functions, FastAPI hosting on Functions, Timer triggers, Key Vault, production configuration, managed identity, deployments, CI/CD, retries, logging, monitoring, or operational hardening.
---
```

Rules：

```text
Functions are stateless.

Persistent state belongs in PostgreSQL.

Use configuration, never hardcoded cloud resources.

Never commit production secrets.

Use Key Vault for production secrets.

Scheduled functions must tolerate duplicate invocation.

Retries must be bounded.

Every external operation needs timeout handling.

Production logs must be structured.

Deployment configuration must be reproducible.
```

---

# 77. Development Phases

## Phase 0 — Foundation

```text
repository scaffold

uv

pyproject

typing

lint

pytest

PostgreSQL

SQLAlchemy

Alembic

GitHub Actions

AGENTS.md

Skills
```

No external integrations.

---

## Phase 1 — Microsoft Authentication + Mail

```text
Microsoft OAuth

MSAL token cache

Graph HTTP client

Mail.Read

message fetch

delta synchronization

mail metadata persistence

idempotency
```

No LLM.

---

## Phase 2 — Normalization + Privacy

```text
HTML normalization

126 forwarded parsing

prefilter

PII sanitizer

URL discovery

tracking removal

privacy tests
```

No LLM.

---

## Phase 3 — Secure Action Links

```text
link extraction

link refs

classification

AES-GCM

Key Vault abstraction

SecureLinkRepository

link privacy tests
```

---

## Phase 4 — LangChain Extraction

```text
Azure OpenAI

LangChain

Pydantic schema

Structured Outputs

prompt versions

validation

fixtures
```

---

## Phase 5 — LangGraph

```text
StateGraph

nodes

routing

Postgres checkpointer

processing runs

interrupt

resume

review items
```

---

## Phase 6 — Domain State Machine

```text
Application resolver

event resolver

ActionItem

state transitions

duplicate detection

reschedule logic

history
```

---

## Phase 7 — Calendar

```text
Calendars.ReadWrite

calendar planner

create

update

idempotency

calendar_links
```

---

## Phase 8 — Daily Brief

```text
query

deterministic renderer

secure link resolution

original email links

Mail.Send

Timer job
```

---

## Phase 9 — Hardening

```text
Key Vault

token encryption

observability

retry policy

E2E

privacy regression

load/error testing

production deployment
```

---

## Phase 10 — Optional Realtime

```text
Graph Webhook

subscription renewal

lifecycle handling

delta reconciliation
```

---

# 78. Phase 0 Codex Prompt

```text
$recruitment-domain
$azure-serverless-ops

Read AGENTS.md and docs/01_FINAL_TECHNICAL_DESIGN.md.

Implement Phase 0 only.

Create the Recruitment Inbox Agent project foundation.

Use:
- Python 3.12+
- uv
- src layout
- strict typing
- Pydantic Settings
- PostgreSQL
- SQLAlchemy 2
- Alembic
- pytest
- pytest-asyncio
- Ruff
- mypy
- GitHub Actions

Create domain interfaces and repository interfaces.

Create the .agents/skills defined in the technical design.

Do not implement:
- Microsoft Graph
- Azure OpenAI
- LangGraph runtime
- Calendar
- Secure Link encryption
- Azure Functions business workflows

Run:

uv run ruff check .
uv run mypy src
uv run pytest

Report:
1. files created
2. architecture decisions
3. test results
4. unresolved Phase 0 issues

Do not implement future phases.
```

---

# 79. Phase 1 Codex Prompt

```text
$graph-mail-calendar
$privacy-email-processing

Read AGENTS.md and docs/01_FINAL_TECHNICAL_DESIGN.md.

Implement Phase 1 only.

Implement:

- Microsoft OAuth Authorization Code Flow
- MSAL integration
- encrypted persistent token-cache abstraction
- Mail.Read delegated permission
- typed Microsoft Graph REST client using httpx
- Graph message retrieval
- Inbox delta query
- pagination
- Retry-After handling
- mail sync state
- SourceEmail metadata persistence
- idempotent ingestion

Do not:

- persist raw email bodies
- implement LLM
- implement Calendar
- implement attachments
- request Mail.ReadWrite

Use respx for Graph HTTP tests.

Cover:
- initial synchronization
- delta synchronization
- pagination
- duplicate email
- expired auth
- Graph 429
- transient Graph failure

Run all quality gates.
```

---

# 80. Phase 2–3 Codex Prompt

```text
$privacy-email-processing
$secure-action-links
$graph-mail-calendar

Implement Phases 2 and 3 only.

Build:

- HTML normalizer
- forwarded 126 parser
- recruitment prefilter
- PII sanitizer
- tracking-content removal
- action link extractor
- action link classifier
- opaque ACTION_LINK refs
- AES-GCM encryption abstraction
- SecureLink persistence

Links must be extracted before sanitization.

Secret-bearing URLs must never:
- enter LLM-ready text
- enter logs
- be stored plaintext

Do not implement LLM calls yet.

Create Chinese and English email fixtures.

Create privacy regression tests.

Run all quality gates.
```

---

# 81. Phase 4 Codex Prompt

```text
$structured-recruitment-extraction
$privacy-email-processing
$secure-action-links

Implement Phase 4 only.

Integrate:

- LangChain
- langchain-openai
- Azure OpenAI
- Pydantic Structured Outputs

Implement RecruitmentExtraction.

Requirements:

- configurable model deployment
- no hardcoded model name
- versioned prompts
- preserve exact datetime source text
- opaque ACTION_LINK refs only
- no plaintext action links
- no silent timezone inference
- deterministic extraction validator

Create contract fixtures for:

assessment
interview
interview without timezone
relative datetime
reschedule
offer
rejection
general update
non-recruitment

Do not implement LangGraph orchestration or Calendar yet.

Run extraction contract tests.
```

---

# 82. Phase 5 Codex Prompt

```text
$langgraph-workflow
$structured-recruitment-extraction
$privacy-email-processing

Implement Phase 5.

Create Recruitment Mail StateGraph.

Nodes:

load_source_email
normalize_email
extract_action_links
prefilter_recruitment
sanitize_content
extract_recruitment_data
validate_extraction
request_review
resolve_application
resolve_existing_event
plan_state_transition
persist_domain_changes
sync_calendar_placeholder
finalize_processing

Use PostgreSQL LangGraph checkpointer.

Implement interrupt/resume for:

timezone ambiguity
application ambiguity
conflicting datetime

Do not store:

raw HTML
OAuth tokens
decrypted SecureLinks

in LangGraph state.

Create graph tests for every branch.

Calendar node remains a typed no-op interface until Phase 7.
```

---

# 83. Definition of Done

最终 V1 必须全部满足：

```text
Outlook OAuth works

Background token refresh works

Graph delta sync works

Duplicate sync is idempotent

126 forwarded mail parses correctly

Raw HTML does not persist

Attachments are not downloaded

Action links are extracted

Secret URLs are encrypted

Secret URLs never reach LLM

PII sanitizer works

LangChain Structured Output works

Assessment extraction works

Interview extraction works

Reschedule extraction works

Offer/rejection extraction works

Timezone ambiguity interrupts workflow

Human review can resume workflow

Application state machine works

Duplicate events do not occur

Reschedule updates existing event

Calendar create works

Calendar update works

Daily Brief works

Daily Brief contains action links

Daily Brief contains original Outlook mail link

Logs contain no sensitive content

PostgreSQL checkpointer works

Interrupted workflow survives restart

Unit tests pass

Graph tests pass

Contract tests pass

Privacy tests pass

E2E tests pass

Ruff passes

mypy passes

CI passes

No production secret exists in Git
```

---

# 84. 最终架构边界

项目完成以后应该可以做到：

```text
Azure OpenAI
       ↓
换 OpenAI / Claude / local model
       ↓
Domain 不变
```

```text
Outlook
 ↓
未来换 Gmail
 ↓
Domain 不变
```

```text
Outlook Calendar
 ↓
未来换 Google Calendar
 ↓
Domain 不变
```

```text
LangGraph
 ↓
未来换 workflow engine
 ↓
Domain 不变
```

因此最终依赖方向必须保持：

```text
Infrastructure
     ↓
Application Services
     ↓
Domain
```

禁止：

```text
Domain
 ↓
Microsoft Graph
```

或：

```text
Domain
 ↓
LangChain
```

---

# 85. Final Architecture Summary

最终正式采用：

```text
126
 ↓
Dedicated Outlook
 ↓
Microsoft Graph
 ↓
Azure Functions
 ↓
LangGraph Workflow
 ├── Email Normalizer
 ├── Secure Action Link Pipeline
 ├── Privacy Sanitizer
 ├── LangChain
 │      ↓
 │  Azure OpenAI
 │
 ├── Deterministic Validator
 ├── Human-in-the-loop
 ├── Application Resolver
 ├── Recruitment State Machine
 └── Calendar Planner
        ↓
    PostgreSQL
        +
 Outlook Calendar

        ↓

Daily Brief
 ├── Interview
 ├── Assessment
 ├── Deadline
 ├── Actions
 ├── Secure Original Action Links
 ├── Original Outlook Email
 └── Needs Review
```

系统的核心价值不是“用了 LangChain”。

而是：

```text
Reliable Email Ingestion
        +
Privacy-preserving Semantic Extraction
        +
Durable LangGraph Workflow
        +
Deterministic Recruitment State Machine
        +
Idempotent Calendar Automation
        +
Secure Action Link Delivery
```

这就是 Recruitment Inbox Agent V1 的最终工程基线。
