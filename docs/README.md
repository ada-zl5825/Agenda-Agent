# Documentation

Start with the [README](../README.md) for product scope and local setup. Agent and coding
constraints live in [AGENTS.md](../AGENTS.md).

| Document | Audience | Contents |
| --- | --- | --- |
| [01_FINAL_TECHNICAL_DESIGN.md](01_FINAL_TECHNICAL_DESIGN.md) | Architecture | Pointer to the canonical design. Read it before changing phase scope. |
| [02_DOMAIN_MODEL.md](02_DOMAIN_MODEL.md) | Domain | `Application` aggregate, company identity, events, actions, idempotency. |
| [03_PRIVACY_MODEL.md](03_PRIVACY_MODEL.md) | Privacy | Sanitization order, encryption, logging, model and calendar boundaries. |
| [04_GRAPH_WORKFLOW.md](04_GRAPH_WORKFLOW.md) | Workflow | LangGraph nodes, Review interrupts, resume, orphan recovery. |
| [05_OPERATIONS.md](05_OPERATIONS.md) | Operators | Settings, Alembic, Azure, timers, console, runbook. |
| [06_TEST_PLAN.md](06_TEST_PLAN.md) | Contributors | What the automated suite must keep covering. |
| [07_OPEN_SOURCE.md](07_OPEN_SOURCE.md) | Maintainers | Checklist before making the repository public. |

Related project files:

| File | Contents |
| --- | --- |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Local development, quality gates, pull requests. |
| [../SECURITY.md](../SECURITY.md) | Vulnerability reporting and security boundaries. |
| [../.env.example](../.env.example) | All application settings. Never commit a real `.env`. |
| [../infra/main.bicep](../infra/main.bicep) | Production Azure topology. |

Alembic head is `20260814_0011`. Apply every schema change with `uv run alembic upgrade head`.
