# Privacy Model

Phases 2 and 3 implement the deterministic privacy boundary before any model integration.

## Processing order

```text
transient Graph body
  -> discover HTTP(S) URLs
  -> classify URLs and replace them with opaque ACTION_LINK references
  -> encrypt original URLs with a versioned AES-256-GCM key
  -> persist ciphertext and approved metadata atomically
  -> normalize HTML/plain text
  -> parse deepest 126/nested forwarded sender context
  -> remove hidden, tracking, footer, and quoted history content
  -> redact every URL and unnecessary PII
  -> produce sanitized future-model text
  -> run the deterministic recruitment prefilter
```

URL discovery happens before HTML normalization because link targets can exist only in `href`
attributes. Phase 3 consumes those `SecretStr`-backed, short-lived values immediately. The
classifier examines host, path, query parameter names and safe context, but never query values.
Each destination is encrypted before persistence and replaced in normalized content by a stable
opaque reference such as `[ACTION_LINK_01: assessment link, domain=example.com]`.

## Removed before the future model boundary

- HTTP(S) URLs and `mailto:` targets;
- personal email addresses and phone numbers;
- labeled candidate/application identifiers;
- Chinese identity-number patterns and labeled passport identifiers;
- labeled student identifiers;
- scripts, styles, hidden HTML, images/tracking pixels;
- common confidentiality/unsubscribe footers and quoted reply history.

## Storage and logging boundary

- Raw HTML and message bodies are never persisted.
- Attachments are never downloaded; only `has_attachments` metadata is retained.
- `FetchedMail`, normalized content, discovered URLs, and sanitized content use safe representations
  so accidental object logging does not reveal body text, private sender addresses, or URL secrets.
- The future LLM boundary may consume only `SecurePreparedEmail.sanitized.text`.
- Plaintext destinations exist only during discovery, encryption, trusted resolution and the
  short-lived normalization replacement call.
- `secure_links` persists only ciphertext, nonce, key version, link type, domain and sanitized
  display text. It has no plaintext URL column.
- Decryption authenticates the source-email ID and opaque ref as AES-GCM associated data, then
  validates that the decrypted hostname matches stored metadata.
- Key Vault access uses the Function App managed identity; key material and decrypted URLs are
  excluded from object representations and logs.
