# Security

## Reporting a vulnerability

Do not open a public GitHub issue for a security problem.

Use [private vulnerability reporting](https://github.com/ada-zl5825/Agenda-Agent/security/advisories/new)
(`Security` → `Report a vulnerability`) and include:

- a description of the issue and its impact
- steps to reproduce, or the affected path / commit
- whether any secret, token, or email content was exposed

Do not attach raw email bodies, OAuth tokens, Key Vault values, or decrypted action URLs.

## Boundaries this project already enforces

- Raw HTML and message bodies are not persisted.
- Attachments are never downloaded.
- OAuth tokens live in an AES-256-GCM cache; they are not logged.
- Secret-bearing URLs are encrypted before persistence. The model receives opaque
  `ACTION_LINK_*` references only.
- LangGraph checkpoints may hold sanitized text, opaque refs, database IDs, and structured
  evidence. They must not hold decrypted URLs, credentials, or raw HTML.
- Review pages never decrypt action links.
- Daily Brief decrypts ordinary action links only at the final render boundary. The stored brief
  audit does not keep rendered HTML or recipients.
- `/api/v1/ops` requires `OPS_API_TOKEN`. Browser surfaces use a signed session and
  action-bound CSRF. OpenAPI is disabled in production.
- Public `GET /health/live` only proves the process can serve HTTP.

## Secrets and keys

These values must never appear in Git, screenshots, or issue text:

- `DATABASE_URL`
- `MICROSOFT_CLIENT_SECRET`
- `TOKEN_CACHE_ENCRYPTION_KEY`
- `WEB_SESSION_SIGNING_KEY`
- `OPS_API_TOKEN`
- Key Vault link-encryption material
- any live Graph or Azure credential

Rotate the affected secret if it may have leaked, including through git history.

## Out of scope for this document

Microsoft, Azure, and model-provider account security are governed by those vendors. This project
does not weaken their terms; operators remain responsible for Entra app consent, mailbox access,
and cloud IAM.
