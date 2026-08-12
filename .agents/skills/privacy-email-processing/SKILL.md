---
name: privacy-email-processing
description: Use whenever email HTML, forwarded messages, PII, logging, storage, attachments, sanitization, model inputs, data retention, or privacy boundaries are changed.
---

# Private Email Processing

Read `docs/01_FINAL_TECHNICAL_DESIGN.md` and the repository `AGENTS.md` before changing email processing.

- Extract action links from raw HTML before sanitization, then discard raw content unless transient processing requires it.
- Never persist raw HTML by default or log raw email bodies.
- Never download attachments in V1 or send them to a model.
- Remove tracking pixels, scripts, styles, hidden content, irrelevant footers, and duplicate quoted content.
- Redact unnecessary phone numbers, email addresses, candidate identifiers, identity-document patterns, and student identifiers.
- Replace sensitive URLs with opaque references before inference.
- Allow only sanitized text to cross the model boundary.
- Record only approved metadata and sanitized error details.
- Add dedicated privacy regression tests for every boundary change.
