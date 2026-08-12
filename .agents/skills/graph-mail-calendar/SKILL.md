---
name: graph-mail-calendar
description: Use when implementing Microsoft OAuth, Microsoft Graph mail retrieval, delta synchronization, Outlook message access, calendar creation or updates, Daily Brief sending, Graph retries, or Graph contract tests.
---

# Graph Mail and Calendar

Read `docs/01_FINAL_TECHNICAL_DESIGN.md` and the repository `AGENTS.md` before changing Microsoft integration.

- Use delegated permissions and least privilege.
- Use `Mail.Read` for mail; do not require `Mail.ReadWrite` for V1.
- Use `Calendars.ReadWrite` for calendar mutations and `Mail.Send` only for Daily Brief delivery.
- Use delta query for incremental synchronization and keep it for reconciliation if webhooks are added later.
- Convert Graph DTOs at the infrastructure boundary; never expose them to domain logic.
- Never log access tokens, refresh tokens, raw email bodies, or secret-bearing URLs.
- Handle delta pagination, bounded retries, timeouts, and `Retry-After`.
- Make Graph writes and ingestion retry-safe and idempotent.
- Test Graph contracts, pagination, throttling, authentication failure, and duplicate delivery.
