---
name: recruitment-domain
description: Use when implementing or changing recruitment applications, application status, assessments, interviews, deadlines, offers, rejections, event matching, duplicate handling, rescheduling, or state transitions.
---

# Recruitment Domain

Read `docs/01_FINAL_TECHNICAL_DESIGN.md` and the repository `AGENTS.md` before changing domain behavior.

- Treat `Application` as the aggregate root.
- Treat email as evidence, not domain state.
- Keep the domain independent from Microsoft Graph, LangChain, LangGraph, Azure OpenAI, Azure Functions, and PostgreSQL implementations.
- Put external boundaries behind typed ports and repository interfaces.
- Never let LLM output directly mutate domain state.
- Make transitions deterministic and every mutation idempotent.
- Update a resolvable existing event for a reschedule; do not create a duplicate event.
- Produce `NEEDS_REVIEW` when application or event resolution is ambiguous.
- Preserve history before replacing or superseding existing values.
- Add tests for transition rules, duplicate handling, and ambiguous resolution.
