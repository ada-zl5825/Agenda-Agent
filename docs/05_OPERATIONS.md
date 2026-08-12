# Phase 0 Operations

Azure Functions hosts a thin ASGI adapter around FastAPI. Functions and routes contain no business logic. Configuration is loaded through typed Pydantic Settings, production secrets are never committed, and persistent state belongs in PostgreSQL.

Apply database changes only through Alembic:

```text
uv run alembic upgrade head
```

Future timers and external calls must be idempotent, timeout-bounded and retry-bounded.

## Production deployment

Production infrastructure is defined in `infra/main.bicep`. It creates:

- an Azure Functions Flex Consumption app running Python 3.12;
- a managed-identity-only Storage account for host state and deployment packages;
- workspace-based Application Insights and Log Analytics;
- a Key Vault containing the database URL, Microsoft client secret, and token-cache key;
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
Microsoft client secret and application encryption secrets, so only run it intentionally.

`deploy-production.yml` runs only for this upstream repository after the `quality` workflow succeeds
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
