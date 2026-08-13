# Operations through Phase 5

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

After the Phase 3.5 migration, idempotently load or reconcile the reviewed starter company catalog
from the same VNet-connected environment:

```text
uv run seed-companies
```

The seed command currently loads 35 reviewed common employers using stable UUIDs and exact
aliases/domains. It does not call external services, perform fuzzy matching, create companies from
observed mail or replace manually reviewed companies. Run it after every catalog update; repeated
execution updates the same seed-owned records without creating duplicates. The operation is
additive: removing an alias or domain from the source catalog does not delete the existing database
record, so retirement requires a separate reviewed catalog mutation.

Future timers and external calls must be idempotent, timeout-bounded and retry-bounded.

## Production deployment

Production infrastructure is defined in `infra/main.bicep`. It creates:

- an Azure Functions Flex Consumption app running Python 3.12;
- a managed-identity-only Storage account for host state and deployment packages;
- workspace-based Application Insights and Log Analytics;
- a Key Vault containing the database URL, Microsoft client secret, token-cache key, and a separate
  action-link encryption key;
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
installations must add the `LINK_ENCRYPTION_KEY` GitHub `production` environment secret before the
next deployment; it must be a base64-encoded random 32-byte value and must not reuse the token-cache
key.

`deploy-azure.yml` runs only for this upstream repository after the `quality` workflow succeeds
on `main`, or through a manual dispatch from `main`. Azure trusts the exact immutable GitHub OIDC
subject built from this repository's owner ID, repository ID, and `production` environment. Forks,
renames, namespace reuse, and pull requests cannot obtain the production Azure token.

The infrastructure deployment is incremental and idempotent: subsequent runs update the same
resources. The concurrency group permits only one production deployment at a time.

Database migrations remain a separate controlled operation because the database has no public
endpoint. The initial template therefore sets `mailSyncEnabled = false`. Run Alembic from a
VNet-connected execution environment, change that parameter to `true`, and deploy again:

```text
uv run alembic upgrade head
```

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
