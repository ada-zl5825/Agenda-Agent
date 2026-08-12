# Privacy Model

Phase 0 establishes these non-negotiable boundaries:

- Do not persist or log raw email HTML or message bodies.
- Do not download attachments in V1.
- Do not put OAuth credentials or secret-bearing URLs in logs or workflow state.
- Only sanitized text may cross a future LLM boundary.
- Extract action links before sanitization and persist secret-bearing URLs only after encryption.

The email and secure-link pipelines are intentionally deferred to Phases 2 and 3.
