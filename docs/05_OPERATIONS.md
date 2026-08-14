# Operations through Phase 9A

Azure Functions hosts a thin ASGI adapter around FastAPI. Functions and routes contain no business logic. Configuration is loaded through typed Pydantic Settings, production secrets are never committed, and persistent state belongs in PostgreSQL.

Apply database changes only through Alembic:

```text
uv run alembic upgrade head
```

## Phase 4 Azure OpenAI

Phase 4 uses an existing Microsoft Foundry or classic Azure OpenAI resource and a model deployment
that supports strict structured outputs. Configure the GitHub `production` environment variables
`AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT`; the deployment workflow passes both to
Bicep. Foundry direct models use an endpoint ending in `/openai/v1` and the deployment name is sent
as the OpenAI `model`. Classic endpoints continue to use API version `2024-10-21`. Calls time out
after 30 seconds, and the three-attempt budget includes the initial request.

The Function App authenticates with its user-assigned managed identity through
`DefaultAzureCredential`; do not configure `AZURE_OPENAI_API_KEY`. Grant that identity
`Cognitive Services User` on a Foundry resource or `Cognitive Services OpenAI User` on a classic
Azure OpenAI resource before enabling processing. Foundry v1 tokens use the
`https://ai.azure.com/.default` scope. Keep the model deployment name in configuration rather than
source code.

Phase 4.5 adds migration `20260813_0005` for append-only company-resolution attempts and ambiguous
candidate evidence. Apply it before enabling Phase 4.5 processing, then run `seed-companies`.
Structured extraction still emits exact `company_raw` and `role_raw` evidence only; the
`RecruitmentEntityResolutionService` owns deterministic resolution, lightweight role normalization
and the idempotent audit write.

Set `LLM_ENABLED=false` for local/test processes that should not call the model. Production Bicep
enables it after the endpoint and deployment variables are supplied. A model invocation failure is
retry-bounded. The Phase 4.5 audit write is safe to retry because its ID is derived from the complete
deterministic source-email outcome and PostgreSQL ignores duplicate attempt and candidate keys.

## Phase 5 durable workflow

Phase 5 adds migration `20260813_0006`. Apply it before starting or resuming mail-processing runs.
It creates `app.processing_runs`, `app.llm_extractions`, `app.review_items` and an isolated
`agent_checkpoint` schema containing the table layout required by the locked
`langgraph-checkpoint-postgres` version.

```text
uv run alembic upgrade head
```

Alembic owns initial checkpoint table creation; application startup must not call checkpointer
`setup()` independently. Upgrade the package and its Alembic table definitions in the same reviewed
change. The production composition opens a PostgreSQL saver with `search_path=agent_checkpoint`,
uses the processing-run UUID as the stable thread ID, and closes the Graph client, Key Vault client,
model credential, checkpointer and SQLAlchemy engine after each invocation.

`run_mail_processing_job` starts one already-ingested source email and
`resume_mail_processing_job` resumes one typed Review decision. Phase 5 intentionally does not add a
second timer that selects pending emails and does not expose a Review mutation route; those require
the later scheduling and authenticated graphical Review phases.

## Phase 6 domain state machine

Phase 6 adds migration `20260813_0007`. It links application-status history, event history, and
action items to their source-email evidence with explicit delete behavior. Apply it before enabling
Phase 6 processing:

```text
uv run alembic upgrade head
```

The production graph resolves and plans in read-only nodes, then writes the Application aggregate,
RecruitmentEvent, ActionItem, and histories in one PostgreSQL transaction. PostgreSQL advisory
transaction locks serialize concurrent creation for one canonical company/role identity; unique
semantic fingerprints and action idempotency keys make retries safe. Do not manually repair these
tables or bypass the workflow with direct SQL. Required but unresolved interview time evidence must
remain in Review and produces no domain write.

Phase 6 sends no Daily Brief and does not expose the future authenticated graphical Review page.

## Phase 7 Outlook Calendar

Phase 7 adds migration `20260813_0008` and delegated Microsoft Graph permission
`Calendars.ReadWrite`. Apply the migration before enabling Calendar writes:

```text
uv run alembic upgrade head
```

For a fresh Entra app registration, `bootstrap-azure.ps1` requests `User.Read`, `Mail.Read`,
`Calendars.ReadWrite`, and `Mail.Send`. For an existing registration, add the delegated
`Calendars.ReadWrite`
permission directly in Entra/Azure Portal or with Azure CLI, then sign in to `/agent` and use
`/auth/mailbox/connect` to complete consent again so the encrypted MSAL cache contains a token for
the expanded scopes. Ordinary `/auth/login` authenticates the console administrator and never
replaces the Graph cache. Do not rerun the
whole bootstrap merely to add this permission: that script intentionally rotates the Microsoft
client secret and application encryption secrets.

Production defaults `CALENDAR_SYNC_ENABLED=false`. After the migration and reauthorization are
complete, set the GitHub `production` environment variable `CALENDAR_SYNC_ENABLED=true` and deploy
from `main`. Leave it false to exercise the full workflow without any Calendar mutation. Optional
durations are `CALENDAR_INTERVIEW_PLACEHOLDER_MINUTES=60` and
`CALENDAR_ASSESSMENT_PLACEHOLDER_MINUTES=30`; descriptions always label them as placeholders.

Calendar calls use bounded Graph retries, `Retry-After`, one forced token refresh after 401,
immutable provider IDs, and create `transactionId` values derived from deterministic event content.
If a user deletes a linked Outlook event, replacement is blocked behind
`UNSAFE_CALENDAR_UPDATE` Review. Daily Brief delivery remains a separate Phase 8 service.

## Phase 8 Daily Brief and graphical Review

Phase 8 adds migration `20260813_0009`, delegated Graph permission `Mail.Send`, a Daily Brief timer,
and authenticated graphical Review routes. Apply the migration first. For an existing Entra app,
add delegated `Mail.Send` and complete `/auth/mailbox/connect` from an authenticated console so the
encrypted MSAL cache contains a token for the expanded scopes. `Mail.ReadWrite` remains forbidden.

Configure a dedicated Base64-encoded random 32-byte `WEB_SESSION_SIGNING_KEY`; it must not reuse
`TOKEN_CACHE_ENCRYPTION_KEY` or the action-link key. `DAILY_BRIEF_RECIPIENT` is an optional bootstrap
value; it can be set in the authenticated console after migration. Keep `DAILY_BRIEF_ENABLED=false`
until migration, recipient setup, and reauthorization are complete. The deployed Function
hostname supplies `PUBLIC_APP_BASE_URL`; local environments must set it explicitly. Linux Flex
Consumption does not support `WEBSITE_TIME_ZONE` or `TZ`, so the six-field NCRONTAB schedule
`0 0 * * * *` wakes hourly in UTC. Application code sends only when `USER_TIMEZONE` reaches
`DAILY_BRIEF_LOCAL_HOUR=8`, including across daylight-saving transitions. The environment recipient
is only the bootstrap value for `app.runtime_controls`; the authenticated `/agent` console can
replace the live recipient with optimistic versioning and CSRF protection without redeployment.

The timer claims at most one send per Microsoft connection and local date. A Graph 202 response is
recorded as accepted. A network or Graph 5xx outcome is recorded as uncertain and is never retried
automatically because the message might already have been accepted. The `app.daily_briefs` audit
stores no rendered HTML, recipient, original email body, or decrypted URL.

`GET /brief/today`, `GET /reviews`, and `GET /reviews/{review_id}` require the signed browser
session established by the Microsoft callback. Review detail GETs are read-only. Resolution POSTs
require a review/version-bound CSRF token, a current optimistic-concurrency version, and a typed
server-validated decision before LangGraph resumes. Review pages expose only secure-link reference,
type, and domain metadata; they never decrypt action URLs.

After the Phase 3.5 migration, idempotently load or reconcile the reviewed starter company catalog
from the same VNet-connected environment:

```text
uv run seed-companies
```

The seed command currently loads 122 reviewed employers using stable UUIDs and exact
aliases/domains, including a reviewed catalog of 100 mainstream China internet majors
(`CHINA_INTERNET_MAJOR_SEEDS` plus the 13 China entries in the foundation catalog). It does not
call external services, perform fuzzy matching, create companies from observed mail or replace
manually reviewed companies. Run it after every catalog update; repeated execution updates the
same seed-owned records without creating duplicates. The operation is additive: removing an alias
or domain from the source catalog does not delete the existing database record, so retirement
requires a separate reviewed catalog mutation. After deploying a catalog expansion, re-run:

```text
./scripts/start-database-maintenance.ps1 -Operation seed-companies
```

Future timers and external calls must be idempotent, timeout-bounded and retry-bounded.

## Phase 9A runtime control and manual operations

Phase 9A adds migration `20260813_0010`, the `app.runtime_controls` source of truth, and the
privacy-safe `app.operation_runs` audit/lease table. Migration `20260814_0011` extends the
allowlisted operation types for manual Daily Brief delivery, creates the independent
`app.admin_identities` allowlist, and adds the versioned Daily Brief recipient to runtime controls.
On upgrade it seeds the currently authorized Microsoft `home_account_id` as the initial administrator.
`ADMIN_MICROSOFT_HOME_ACCOUNT_ID` is an optional explicit bootstrap/recovery override, not a secret.
Apply all migrations before deploying the matching application code:

```text
uv run alembic upgrade head
```

Timer and dispatcher composition fails closed when this control table is unavailable: no mail,
workflow, Calendar, or Brief side effect is attempted. This makes a schema/configuration outage
visible through protected readiness and status without silently bypassing the runtime kill switch.

The control plane is available under `/api/v1/ops` and requires
`Authorization: Bearer <OPS_API_TOKEN>`. `OPS_API_TOKEN` is an independent base64-encoded 32-byte
random secret stored in Key Vault; it must not reuse any encryption or signing key. The API never
returns OAuth tokens, Graph message IDs, subjects, bodies, recipients, secure URLs, or decrypted
links. Public `GET /health/live` proves only that the process can serve HTTP. Protected
`GET /health/ready` checks PostgreSQL and the presence of an authorized Microsoft connection.

Available control and observation routes are:

- `GET /api/v1/ops/control` and `PATCH /api/v1/ops/control`;
- `GET /api/v1/ops/status`;
- `POST /api/v1/ops/operations/mail-sync`;
- `POST /api/v1/ops/operations/process-email/{source_email_id}`;
- `POST /api/v1/ops/operations/process-pending` with a bounded `1..100` limit;
- `POST /api/v1/ops/operations/daily-brief` for idempotent same-day delivery;
- `POST /api/v1/ops/operations/reset-mail-cursor`; and
- `GET /api/v1/ops/operations/{operation_id}`.

Every POST requires a caller-generated `Idempotency-Key` containing 8 to 128 ASCII characters and
returns `202 Accepted` with an operation ID. HTTP requests never wait for Graph or the LangGraph
workflow. The Azure Storage Queue message contains only that opaque operation ID; the worker reads
all command parameters from PostgreSQL, claims a 25-minute lease, and uses the platform's bounded
delivery attempts. Reusing the same key returns the same operation and may safely redeliver its
opaque queue message; the database lease prevents a second execution and also closes the
database-created/queue-send failure window. A once-per-minute dispatcher re-enqueues any operation
still marked `queued` or holding an expired worker lease, so an HTTP disconnect, worker crash, or
Storage transient cannot strand accepted work.
Batch processing creates deterministic child operations, and each source email is claimed
atomically before its workflow begins.

Runtime changes use optimistic concurrency: read the current `version`, then send it as
`expected_version` with a required reason (`manual`, `testing`, `maintenance`, `incident`, or
`account_switch`). Calendar writes cannot be enabled while workflow processing is paused. Cursor
reset is intentionally rejected unless both mail synchronization and workflow processing are
paused. Environment booleans initialize the control row once; after that, PostgreSQL controls the
live state without a resource deployment.
Status also reports capability ceilings. Workflow processing requires a configured enabled model;
Calendar cannot be enabled unless the deployment has `CALENDAR_SYNC_ENABLED=true`; Daily Brief
cannot be enabled until its recipient, public base URL, and independent web-session key are
configured. These checks prevent a runtime switch from claiming an external side effect is active
when its cloud boundary is unavailable.

### Authenticated visual control console

`GET /agent` is the signed-session browser surface for the same application service. Opening `/`
redirects to it, and an unauthenticated visitor completes allowlisted Microsoft administrator login
before returning to the console. This login discards its temporary MSAL cache and does not change
the Agent mailbox. Only `/auth/mailbox/connect`, started from an existing administrator session,
may replace the encrypted Graph cache. The browser never receives `OPS_API_TOKEN`; the server
verifies that the signed session is bound to the configured connection and invokes the Phase 9A
service directly.

The page displays only privacy-safe operational data: database and OAuth readiness, the four
runtime switches and capability ceilings, mail-sync cursor/timestamps/error code, aggregate source,
workflow and operation counts, open Review count, latest Brief audit state, and the selected opaque
operation status. The explicitly configured Daily Brief recipient is visible only to an authenticated
administrator in its settings panel. The page never renders message IDs, subjects, bodies, OAuth
credentials, decrypted links, Graph DTOs, prompts, or model output.

The console supports:

- optimistic, PostgreSQL-backed mail-sync, workflow, Calendar-write and Daily-Brief switches;
- explicit Outlook connection/replacement that is separate from administrator login;
- viewing and updating the versioned Daily Brief recipient without an Azure deployment;
- idempotent manual mail synchronization;
- bounded pending-workflow fan-out; and
- idempotent manual delivery of today's Daily Brief.

Every browser mutation is a same-origin form protected by a CSRF token bound to the signed session,
typed action and current control version. Manual actions create an `operation_runs` row and enqueue
only its opaque UUID; the HTTP request never waits for Graph, LangGraph or Brief delivery. A manual
Daily Brief still uses the existing at-most-once `(account_id, brief_date)` claim, so clicking twice
cannot send a duplicate successful Brief.

Example PowerShell smoke sequence (do not paste the token into logs or source control):

```powershell
$headers = @{
  Authorization = "Bearer $env:OPS_API_TOKEN"
  "Idempotency-Key" = "manual-sync-20260813-001"
}
Invoke-RestMethod "$env:AGENDA_AGENT_URL/health/ready" -Headers $headers
$operation = Invoke-RestMethod `
  "$env:AGENDA_AGENT_URL/api/v1/ops/operations/mail-sync" `
  -Method Post -Headers $headers
Invoke-RestMethod `
  "$env:AGENDA_AGENT_URL/api/v1/ops/operations/$($operation.id)" `
  -Headers @{ Authorization = "Bearer $env:OPS_API_TOKEN" }
```

For a stability test, verify liveness and readiness, trigger one mail sync twice with the same
idempotency key, confirm the same operation ID is returned, wait for `succeeded`, then submit a
small `process-pending` batch. Confirm source/workflow counts converge, Review items are visible on
the graphical Review page, Calendar writes match the runtime switch, and no unexpected duplicate
Application, event, action, Calendar, or Brief rows are created. Pause all switches to test the
kill switch. Test cursor reset only in that paused state, then resume mail sync and verify a full
delta reconciliation remains idempotent.

## Production deployment

Production infrastructure is defined in `infra/main.bicep`. It creates:

- an Azure Functions Flex Consumption app running Python 3.12;
- a managed-identity-only Storage account for host state and deployment packages;
- workspace-based Application Insights and Log Analytics;
- a Key Vault containing the database URL, Microsoft client secret, token-cache key, a separate
  action-link encryption key, a separate web-session signing key, and a separate operations API
  token;
- a PostgreSQL Flexible Server on a delegated private subnet; and
- a VNet-integrated Function App with no public route to PostgreSQL.

No production secret is committed to Git. The one-time bootstrap command creates a resource-group-
scoped deployment identity, its GitHub OIDC federated credential, a Microsoft application
registration, and the GitHub `production` environment configuration:

```powershell
./scripts/bootstrap-azure.ps1 -ResourceGroupName "rg-agenda-agent-prod-uks"
```

The command requires Azure CLI and GitHub CLI authentication. It generates all application secrets
locally and writes them directly to GitHub environment secrets. Re-running the command rotates the
Microsoft client secret and application encryption secrets, so only run it intentionally. Existing
installations must add `OPS_API_TOKEN` to the GitHub `production` environment before the next
infrastructure deployment. It must be an independent base64-encoded random 32-byte value and must
not reuse the token-cache, action-link, or web-session key.

`deploy-app.yml` publishes ordinary application changes after `quality` succeeds. Its scope check
skips the deployment when the verified revision changes `alembic/**`, `infra/**`,
`scripts/bootstrap-azure.ps1`, or `deploy-infra.yml`; in that case `deploy-infra.yml` validates and
incrementally deploys Bicep and builds the matching immutable database-maintenance image. For a
schema change, it deliberately holds the Function package: run the `migrate` Job, verify success,
then manually dispatch `deploy-production-app`. The infrastructure workflow can also be manually
dispatched from `main`, but it does not run for ordinary code-only changes. Azure trusts the exact
immutable GitHub OIDC
subject built from this repository's owner ID, repository ID, and `production` environment. Forks,
renames, namespace reuse, and pull requests cannot obtain the production Azure token.

The infrastructure deployment is incremental and idempotent: subsequent runs update the same
resources. The concurrency group permits only one production deployment at a time.

Database migrations remain a separate controlled operation because the database has no public
endpoint. Production therefore includes a manual Azure Container Apps Job in the same VNet. It
uses a dedicated user-assigned managed identity to pull its image from ACR and resolve only the
`database-url` Key Vault secret. No VM, public PostgreSQL endpoint, registry password, or database
credential is created. The Job has one replica, no automatic retry for an uncertain migration,
and an application-level PostgreSQL advisory lock to serialize schema/catalog mutations.

The Job accepts only `check`, `migrate`, and `seed-companies`; it never accepts arbitrary SQL or a
shell command. Start it from any authenticated workstation with:

```powershell
./scripts/start-database-maintenance.ps1 -Operation check
./scripts/start-database-maintenance.ps1 -Operation migrate
./scripts/start-database-maintenance.ps1 -Operation seed-companies
```

`check` runs `alembic current --check-heads` without taking the mutation lock. `migrate` runs
`alembic upgrade head`, and `seed-companies` invokes the idempotent reviewed company catalog seed;
the latter two hold the advisory lock for the complete operation. Each trigger creates an auditable
Container Apps Job execution and then scales back to zero. Inspect an execution with the command
printed by the script or in Azure Portal under Container Apps Jobs.

The infrastructure workflow creates the dedicated `/27` Container Apps subnet, Basic ACR,
managed environment, identity/RBAC, immutable revision-tagged image, and manual Job. It runs only
for the infrastructure deployment path; ordinary application deployments do not rebuild these
resources. Keep the initial runtime controls disabled until `migrate` and the required seed have
succeeded:

```text
./scripts/start-database-maintenance.ps1 -Operation migrate
```

## Reliability runbook (2026-08-14 revision)

Design chapter 86 of the canonical design document records the reliability decisions behind this
runbook; chapter 87 records the reviewed-and-accepted trade-offs; chapter 88 records the 126
forward, datetime-override, and duplicate-calendar revisions. Operational consequences:

- **Mail sync**: a `SYNC_IN_PROGRESS` failure code on a manual operation means a concurrent
  synchronization held the 10-minute lease; the operation retries automatically. A
  `DELTA_STATE_INVALID` failure clears the cursor itself; the next scheduled run performs a full
  resync without manual `reset-mail-cursor`. `SYNC_PAGE_LIMIT` is progress-preserving: the next
  run continues from the committed cursor.
- **Daily Brief**: `BRIEF_DISPATCH_ABANDONED` marks a crashed in-flight dispatch that was closed
  as `uncertain`; it is never retried automatically because the Graph outcome is unknown. Confirm
  in the mailbox Sent Items whether the brief left, then decide manually. A `failed` brief retries
  automatically the same local day (three claims maximum), including late catch-up ticks after the
  configured local hour.
- **Source emails**: `needs_review` is a first-class processing status meaning "waiting on a
  human"; such emails are excluded from retries and `process-pending` batches until their review
  is resolved. Unparsed interview times now take two reviews: timezone first, then
  `YYYY-MM-DD HH:MM` (`use_override`). A run failing with `EVENT_DATETIME_UNRESOLVED` after
  that override means the supplied clock is still unusable; open the same review URL (the
  resolve POST redirects there with `error=`) and correct the value, or ignore the item.
  Emails already marked `failed` before this revision do not resume in place. Submit
  `process-pending` so a new `processing_run_id` is created, then complete both reviews.
  `/brief/today` is the live preview; a Daily Brief email already sent that local day is
  at-most-once and will not rewrite. Active `offer` / `rejection` / `application_received`
  events appear under `NEW UPDATES`.

### One-time cleanup after the Base64 queue fix

Messages sent before the Base64 producer fix are permanently undecodable and were moved to the
poison queue. They contain only opaque operation UUIDs, so clearing them is safe. From an
authenticated Azure CLI session:

```powershell
$rg = "rg-agenda-agent-prod-uks"
$account = az storage account list -g $rg --query "[0].name" -o tsv
az storage message clear --queue-name recruitment-operations-poison `
  --account-name $account --auth-mode login
```

### Verifying queue-worker scale-out

The dispatch timer executes due operations inline as a scale fallback, so the console works even
when the queue trigger never fires. To confirm whether the queue path recovered after the Base64
fix, check Application Insights for `operations_queue_worker` invocations:

```text
requests
| where timestamp > ago(24h)
| where operation_Name == "operations_queue_worker"
| summarize count(), max(timestamp)
```

If invocations appear, the queue trigger is the low-latency path again and the timer fallback only
handles stragglers. If none appear after submitting a manual operation, operations still complete
through the fallback within roughly one minute; investigate the Flex Consumption scale controller
before removing the fallback.

## Phase 3 key handling

The deployment stores `LINK_ENCRYPTION_KEY` as the versioned Key Vault secret
`recruitment-link-encryption-key`. The Function App receives only the vault URL and secret name, and
reads the secret with its user-assigned managed identity and the `Key Vault Secrets User` role.
Encryption records the Key Vault version so older links remain decryptable after rotation.

Generate a new value without printing or committing it, store it in the GitHub `production`
environment as `LINK_ENCRYPTION_KEY`, and deploy through the workflow. Run the Phase 3 Alembic
migration from the same VNet-connected execution environment before enabling processing:

```text
uv run alembic upgrade head
```
