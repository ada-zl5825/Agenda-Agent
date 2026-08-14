# Privacy Model

Phases 2 and 3 implement the deterministic privacy boundary. Phase 4 consumes only its safe output,
and Phases 5/6 checkpoint only the reduced privacy-safe workflow state and typed domain intent.

## Processing order

```text
transient Graph body
  -> discover HTTP(S) URLs
  -> classify URLs and replace them with opaque ACTION_LINK references
  -> encrypt original URLs with a versioned AES-256-GCM key
  -> persist ciphertext and approved metadata atomically
  -> normalize HTML/plain text
  -> parse deepest 126/nested forwarded sender context
  -> remove hidden, tracking, footer, and quoted reply history
     (keep Outlook `#divRplyFwdMsg` envelopes that still contain From/发件人
     plus Sent/Subject; those are the original recruiter, not quoted history)
  -> redact every URL and unnecessary PII
  -> produce sanitized model text
  -> run the deterministic recruitment prefilter
  -> invoke strict structured extraction with sanitized text and opaque link refs only
  -> deterministically validate model evidence
```

URL discovery happens before HTML normalization because link targets can exist only in `href`
attributes. Phase 3 consumes those `SecretStr`-backed, short-lived values immediately. The
classifier examines host, path, query parameter names and safe context, but never query values.
Each destination is encrypted before persistence and replaced in normalized content by a stable
opaque reference such as `[ACTION_LINK_01: assessment link, domain=example.com]`.

## Removed before the model boundary

- HTTP(S) URLs and `mailto:` targets;
- personal email addresses and phone numbers;
- labeled candidate/application identifiers;
- Chinese identity-number patterns and labeled passport identifiers;
- labeled student identifiers;
- scripts, styles, hidden HTML, images/tracking pixels;
- common confidentiality/unsubscribe footers and quoted reply history.
  Outlook `#divRplyFwdMsg` blocks that still carry From/发件人 plus Sent/Subject
  are forward envelopes and stay in the normalized text so the original recruiter
  can be recovered. Consumer mailbox domains never become employer identity.

## Storage and logging boundary

- Raw HTML and message bodies are never persisted.
- Attachments are never downloaded; only `has_attachments` metadata is retained.
- `FetchedMail`, normalized content, discovered URLs, and sanitized content use safe representations
  so accidental object logging does not reveal body text, private sender addresses, or URL secrets.
- The Phase 4 model boundary may consume only `SecurePreparedEmail.sanitized.text`, the
  timezone-aware message `received_at`, the prompt version and allowed opaque link references.
- A final input guard rejects plaintext HTTP(S)/www material, secret query fragments, malformed or
  cross-email link references, and opaque references that were not secured for the source email.
- The model returns evidence only. It never receives or chooses `company_id`, mutates PostgreSQL,
  resolves secure destinations, changes workflow state, creates calendar events or sends email.
- Provider failures are translated to a stable privacy-safe application error without propagating
  model input or provider response content.
- Phase 5 graph context carries live service objects outside checkpoint state. Checkpoints may hold
  sanitized text, opaque link refs, database IDs, structured extraction/validation evidence and
  processing metadata only.
- Phase 6 resolution and transition plans may hold sanitized structured evidence, deterministic
  fingerprints, database IDs, and opaque link refs. They never hold encrypted-link plaintext,
  OAuth credentials, raw HTML/body, or attachments. Persistence resolves an opaque ref directly to
  its encrypted `secure_links` row inside the domain transaction.
- `processing_runs`, `llm_extractions` and `review_items` never persist raw HTML/body, attachments,
  prompt/completion text, OAuth credentials, decrypted URLs or complete checkpoint payloads.
- Interrupt payloads contain only a review ID, stable reason/type, typed question and allowed
  choices. A resume decision is deterministically validated before its optimistic database update.
- Plaintext destinations exist only during discovery, encryption, trusted resolution and the
  short-lived normalization replacement call.
- `secure_links` persists only ciphertext, nonce, key version, link type, domain and sanitized
  display text. It has no plaintext URL column.
- Decryption authenticates the source-email ID and opaque ref as AES-GCM associated data, then
  validates that the decrypted hostname matches stored metadata.
- Key Vault access uses the Function App managed identity; key material and decrypted URLs are
  excluded from object representations and logs.
- Phase 7 Calendar descriptions are built only from canonical company/role metadata, validated
  event fields, sanitized source-time evidence, and an allowlisted Outlook web link with query and
  fragment removed. Calendar planning never loads `secure_links`, decrypted action URLs, raw email
  content, attachments, OAuth tokens, prompts, or model completions.
- Graph Calendar responses are reduced immediately to an opaque immutable event ID. Graph error
  bodies and event descriptions are not logged or checkpointed; graph state retains only the
  operation and a stable privacy-safe reason.
- Phase 8 Review HTML never decrypts action links. Daily Brief decrypts ordinary action links only
  at the final render boundary. `daily_briefs` stores send status and a safe error code, not
  rendered HTML, recipients, or plaintext URLs.
- Phase 9A `/agent` and `/api/v1/ops` expose aggregate counts, readiness, and opaque operation IDs.
  They never render message IDs, subjects, bodies, OAuth credentials, decrypted links, prompts, or
  model completions. The Daily Brief recipient is visible only to an authenticated administrator.
