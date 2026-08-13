# Test Plan through Phase 4.5

The automated suite covers:

- domain invariants and timezone-aware datetimes;
- settings, FastAPI health/OAuth routes, and Azure deployment packaging;
- SQLAlchemy metadata and offline Alembic migration compilation;
- MSAL encrypted cache behavior and Graph delta/retry contracts;
- idempotent mail synchronization;
- HTML/plain-text normalization;
- Chinese 126 forwarding and English nested-forward precedence;
- hidden content, tracking pixels, scripts, footers, and quoted-history removal;
- pre-sanitization URL discovery without secret-bearing representations;
- email, phone, candidate, government, passport, and student-ID redaction;
- subject and body sanitization before the future model boundary;
- high-recall recruitment prefilter outcomes;
- deterministic repeated preparation and the attachment-download prohibition;
- deterministic classification for every Phase 3 action-link type;
- stable opaque references and sanitized link display metadata;
- AES-256-GCM round trips, context binding, domain validation and key-version lookup;
- Key Vault timeout and secret-decoding behavior without secret-bearing representations;
- secure email preparation with no plaintext URL or token in model text, metadata or logs; and
- Alembic `secure_links` schema privacy and idempotent repository replacement;
- company/domain normalization and entity invariants;
- exact canonical-name, alias and sender-domain company resolution;
- unresolved, non-fuzzy and ambiguous company outcomes;
- cross-evidence name/domain conflict detection without silent precedence;
- company resolution result fields, raw evidence preservation and confidence provenance;
- lightweight role normalization with raw role preservation and coarse families;
- Phase 4 `VALID` and `NEEDS_REVIEW` output flowing into Phase 4.5 while `INVALID` output is rejected;
- stable retry-idempotent resolution audit IDs and ambiguous candidate persistence;
- stable parent-child seed IDs and repeatable catalog seeding;
- `Application.company_id` identity with unchanged `raw_company_name` evidence; and
- Phase 3.5 migration preservation plus PostgreSQL repository lookups;
- strict structured-output schema completeness without `company_id` or canonical company fields;
- nine extraction contracts: assessment, interview, interview without timezone, relative datetime,
  reschedule, offer, rejection, general update and non-recruitment;
- deterministic `VALID`, `NEEDS_REVIEW` and `INVALID` outcomes for confidence, timezone, evidence,
  action and opaque-link consistency;
- rejection of plaintext URLs, token-like query fragments, malformed references and hallucinated
  action-link references before or after the model call;
- proof that the LangChain adapter receives only sanitized text, received time, prompt version and
  allowed opaque link references;
- privacy-safe provider failures and representations; and
- managed-identity Azure OpenAI deployment settings with no API key.

The Docker-backed PostgreSQL migration/upsert tests run when `RUN_POSTGRES_INTEGRATION=1`.
They cover Graph email metadata, encrypted secure-link persistence, company seed idempotency,
legacy application company-name migration and Phase 4.5 audit/candidate idempotency.

The Phase 4 contract suite is provider-independent and runs without network access or Azure
credentials. It validates saved structured outputs against the current Pydantic schema and the
deterministic validator. Live-model evals may be run separately, but cannot replace these contracts.

Future Phase 5/8 review and Daily Brief tests must verify that every `NEEDS REVIEW` item has an
authenticated `/reviews/{review_id}` graphical deep link; link preview or GET requests have no side
effects; wrong-account access is denied; stale/double resolution is idempotent; allowed choices and
typed overrides are server-validated; and no raw body, PII, checkpoint state or decrypted secure URL
appears in HTML, DOM, query parameters, logs or sent email.
