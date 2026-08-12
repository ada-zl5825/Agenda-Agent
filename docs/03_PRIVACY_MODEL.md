# Privacy Model

Phase 2 implements the deterministic privacy boundary before any model integration.

## Processing order

```text
transient Graph body
  -> discover HTTP(S) URLs
  -> normalize HTML/plain text
  -> parse deepest 126/nested forwarded sender context
  -> remove hidden, tracking, footer, and quoted history content
  -> redact every URL and unnecessary PII
  -> produce sanitized future-model text
  -> run the deterministic recruitment prefilter
```

URL discovery must happen before HTML normalization because link targets can exist only in `href`
attributes. Phase 2 retains those exact values only in `SecretStr`-backed, short-lived objects for the
future Phase 3 encryption boundary. It does not classify, persist, or log them.

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
- The future LLM boundary may consume only `PreparedEmail.sanitized.text`.
- Phase 3 must consume discovered URLs, replace them with opaque references, encrypt the originals,
  and persist only ciphertext plus approved metadata.
