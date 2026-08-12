---
name: langgraph-workflow
description: Use when implementing or changing the Recruitment Inbox LangGraph, graph state, nodes, routing, checkpoints, interrupts, human review, resume behavior, workflow retries, or graph tests.
---

# Recruitment LangGraph Workflow

Read `docs/01_FINAL_TECHNICAL_DESIGN.md` and the repository `AGENTS.md` before changing workflow orchestration.

- Use `StateGraph` with explicit nodes, routes, and terminal branches.
- Treat graph state as execution state, not business state; keep PostgreSQL domain data authoritative.
- Keep raw HTML, OAuth credentials, decrypted secure links, and attachments out of graph state.
- Keep nodes small and deterministic where possible.
- Invoke the LLM only in a dedicated typed extraction node.
- Validate extraction before any database or calendar side effect.
- Use `interrupt` only for genuine human decisions and make every interrupted workflow resumable.
- Make retries safe around all side-effecting nodes.
- Test every branch, interrupt, resume path, and failure boundary.
