# Recruitment Inbox Agent

Follow `docs/01_FINAL_TECHNICAL_DESIGN.md`. Human-facing setup and the document map start in
`README.md` and `docs/README.md`.

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

Do not place decrypted secret URLs, OAuth credentials, raw email HTML, or attachments in graph state.

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

Ambiguous time must enter `NEEDS_REVIEW`.

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

```text
uv run ruff check .
uv run mypy src
uv run pytest
```

Do not claim completion unless all required checks pass.

## Scope

Do not implement future phases without explicit instruction.

Do not add Gmail, IMAP, browser automation, automatic recruiter replies, or attachment ingestion unless explicitly requested.
