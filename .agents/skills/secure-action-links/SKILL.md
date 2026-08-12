---
name: secure-action-links
description: Use when extracting, classifying, encrypting, storing, resolving, rendering, or testing assessment links, interview links, confirmation links, meeting links, scheduling links, or other secret-bearing recruitment URLs.
---

# Secure Recruitment Action Links

Read `docs/01_FINAL_TECHNICAL_DESIGN.md` and the repository `AGENTS.md` before changing action-link handling.

- Extract links before content sanitization and allow only explicitly supported URL schemes.
- Replace links with opaque `ACTION_LINK_*` references before any model call.
- Never expose plaintext secure links to models, logs, graph state, or plaintext database columns.
- Encrypt secret-bearing URLs before persistence and store domain, link type, nonce, and key version separately.
- Keep secret URL query data out of calendar descriptions.
- Decrypt only at the final trusted rendering boundary and only for the lifetime of that operation.
- Treat decrypted destinations as untrusted external URLs even when their ciphertext came from the database.
- Test URL classification, unsupported schemes, encryption boundaries, redaction, and log safety.
