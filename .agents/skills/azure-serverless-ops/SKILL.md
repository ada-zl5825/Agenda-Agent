---
name: azure-serverless-ops
description: Use when implementing Azure Functions, FastAPI hosting on Functions, Timer triggers, Key Vault, production configuration, managed identity, deployments, CI/CD, retries, logging, monitoring, or operational hardening.
---

# Azure Serverless Operations

Read `docs/01_FINAL_TECHNICAL_DESIGN.md` and the repository `AGENTS.md` before changing operational infrastructure.

- Keep Azure Functions stateless and place persistent state in PostgreSQL.
- Keep business logic out of Function entrypoints and FastAPI routes; invoke application services instead.
- Configure cloud resources and model deployments through validated settings, never hardcoded values.
- Never commit production secrets; use Azure Key Vault and managed identity in production.
- Make timer-triggered and retried operations idempotent.
- Apply explicit timeouts and bounded retries to every external operation.
- Emit structured, privacy-safe logs without tokens, message bodies, PII, or secret-bearing URLs.
- Keep deployment and schema migration configuration reproducible.
- Add operational tests for configuration validation, duplicate invocation, retry limits, and failure reporting.
