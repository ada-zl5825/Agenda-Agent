# Contributing

This repository follows [AGENTS.md](AGENTS.md) and
[docs/01_FINAL_TECHNICAL_DESIGN.md](docs/01_FINAL_TECHNICAL_DESIGN.md). Read both before changing
architecture or phase scope. Participation is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and PostgreSQL.

```powershell
Copy-Item .env.example .env
uv sync --all-groups --locked
uv run alembic upgrade head
uv run seed-companies
uv run uvicorn recruitment_agent.api.app:app --reload
```

Do not commit `.env` or `local.settings.json`. Generate independent 32-byte keys for the token
cache, web session, and operations token. Never reuse one key for two purposes.

## Quality gates

Every change that touches production code must pass:

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
```

PostgreSQL integration tests are optional and need Docker:

```powershell
$env:RUN_POSTGRES_INTEGRATION="1"
uv run pytest -m integration
```

A production bug requires a regression test in the same change.

## Architecture rules

- Keep domain logic independent from Microsoft Graph, LangChain, LangGraph, Azure OpenAI, Azure
  Functions, and PostgreSQL implementations.
- Routes and Function entrypoints call application services only. They contain no business logic.
- LangGraph state is execution state. PostgreSQL domain tables are the source of truth.
- LLMs extract typed evidence only. They never mutate the database, calendar, email, or secure
  links. Every model output is validated deterministically.
- Never silently infer timezone. Ambiguous time enters `NEEDS_REVIEW`.
- Never log raw email bodies, OAuth tokens, or plaintext secret-bearing URLs.
- Never send attachments to the model. Only sanitized text may cross the model boundary.
- Extract action links before sanitization. Persist ciphertext. The model sees `ACTION_LINK_*`
  references only.
- All ingestion and mutations must be idempotent. Use Alembic for every schema change.

## Scope

Do not implement future phases without an explicit request. Do not add Gmail, IMAP, browser
automation, automatic recruiter replies, or attachment ingestion unless asked.

## Pull requests

- Keep the change focused. Do not mix a feature with unrelated refactors.
- Update the matching document in `docs/` when behavior, operations, or privacy boundaries change.
- Describe why the change exists, not only what files moved.
- Do not include secrets, production hostnames you do not intend to publish, or raw email content.
- Security reports go through [SECURITY.md](SECURITY.md), not a public issue.
