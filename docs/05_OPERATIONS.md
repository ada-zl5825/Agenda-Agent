# Phase 0 Operations

Azure Functions hosts a thin ASGI adapter around FastAPI. Functions and routes contain no business logic. Configuration is loaded through typed Pydantic Settings, production secrets are never committed, and persistent state belongs in PostgreSQL.

Apply database changes only through Alembic:

```text
uv run alembic upgrade head
```

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
