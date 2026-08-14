# Test Plan through Phase 9A

The automated suite covers:

- domain invariants and timezone-aware datetimes;
- settings, FastAPI health/OAuth routes, and Azure deployment packaging;
- SQLAlchemy metadata and offline Alembic migration compilation;
- MSAL encrypted cache behavior and Graph delta/retry contracts;
- idempotent mail synchronization;
- HTML/plain-text normalization;
- Chinese 126 forwarding, English nested-forward precedence, and Outlook `#divRplyFwdMsg`
  wraps that split `From:` from the address line;
- consumer mailbox domains (`126.com` and siblings) never winning employer domain match,
  and recruiter replies that quote a 126 address keeping the Graph author;
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
- nine extraction contracts: assessment, interview, interview without timezone
  (wall-clock extracted, timezone review only), relative datetime,
  reschedule, offer, rejection, general update and non-recruitment;
- deterministic `VALID`, `NEEDS_REVIEW` and `INVALID` outcomes for confidence, timezone, evidence,
  action and opaque-link consistency;
- rejection of plaintext URLs, token-like query fragments, malformed references and hallucinated
  action-link references before or after the model call;
- proof that the LangChain adapter receives only sanitized text, received time, prompt version and
  allowed opaque link references;
- privacy-safe provider failures and representations; and
- managed-identity Azure OpenAI deployment settings with no API key;
- every Phase 5 route: happy path, unlikely prefilter, model irrelevance, invalid extraction,
  timezone confirmation of an extracted wall-clock, Application ambiguity,
  datetime override only when the clock is still missing,
  and workflow-failure redirect with `error=EVENT_DATETIME_UNRESOLVED`;
- invalid Review choice loops, typed resume, stable Review identity and optimistic idempotency;
- graph reconstruction with the same checkpointer and processing-run/thread identity;
- exact application resolution, explicit application ambiguity, and reviewed create-new behavior;
- semantic event/action duplicate detection across repeated processing, including dated
  fingerprints only (two undated interviews do not collapse);
- same-round interview time changes updating the existing event (`interview_time_changed`);
- deterministic status transitions and terminal-state downgrade prevention;
- single-target reschedule updates, ambiguous reschedule interrupts, and old-value history;
- unresolved required datetime/timezone evidence produces a zero-mutation plan;
- Phase 6 transition plans retain opaque link refs and never plaintext secure URLs;
- Phase 7 Calendar eligibility, deterministic subject/body planning, explicit placeholder
  durations, create/update/unchanged paths, transaction idempotency, and missing-event Review;
- Graph Calendar POST/PATCH payloads, immutable IDs, URL escaping, bounded retries, 401 refresh,
  404 handling, and `Retry-After` behavior;
- Calendar descriptions exclude action tokens, untrusted URLs and source-link query strings;
- `calendar_links` uniqueness metadata and Phase 7 Alembic upgrade/downgrade compilation;
- deterministic Daily Brief section ordering, HTML escaping, timezone rendering, and empty state;
- ordinary action-link decryption only at the final Brief boundary while Review links remain opaque;
- same-day dispatch idempotency plus accepted, failed, and uncertain send auditing without content;
- Graph `sendMail` payload, 202 acceptance, 401 refresh, safe 429 retry, and no-retry 5xx boundary;
- signed session expiry/tamper rejection, safe return paths, and review/version-bound CSRF;
- graphical Review authentication, privacy-safe fields, wrong-account denial, typed choices,
  optimistic versions, workflow resume, and read-only resolved state;
- Phase 8 migration, `Mail.Send`, Timer, Key Vault, and disabled-by-default deployment configuration;
- graph-state, object-representation and failure-audit privacy regressions; and
- isolated PostgreSQL checkpoint connection configuration;
- bearer-protected liveness/readiness separation and operations routes;
- runtime-control optimistic versions and Calendar/workflow safety invariants;
- idempotent command submission, opaque queue messages, leases, bounded retries and batch fan-out;
- paused-state-only delta cursor reset and privacy-safe status projections; and
- application-only versus infrastructure deployment scope selection.

The visual Phase 9A console tests additionally cover signed-session redirects, action/version-bound
CSRF, account scoping, escaped privacy-safe HTML, optimistic switch updates, bounded manual workflow
fan-out, idempotent operation keys, asynchronous status rendering, and same-day Daily Brief delivery.
They also prove that administrator login discards its temporary MSAL cache, explicit mailbox
connection is bound to the initiating admin session, unapproved administrators are rejected,
recipient changes are normalized/versioned, and a real mailbox identity change clears the previous
delta cursor in the optional PostgreSQL integration suite.

The Docker-backed PostgreSQL migration/upsert tests run when `RUN_POSTGRES_INTEGRATION=1`.
They cover Graph email metadata, encrypted secure-link persistence, company seed idempotency,
legacy application company-name migration, Phase 4.5 audit/candidate idempotency, a Phase 5
PostgreSQL interrupt/close/reopen/resume flow, and Phase 6 retry/reschedule persistence with
application/event/action/history cardinality assertions. Phase 8 adds an empty account-scoped Brief
snapshot plus same-day dispatch-claim and accepted-audit idempotency check.

The Phase 4 contract suite is provider-independent and runs without network access or Azure
credentials. It validates saved structured outputs against the current Pydantic schema and the
deterministic validator. Live-model evals may be run separately, but cannot replace these contracts.

Phase 8 contract tests verify that every `NEEDS REVIEW` item has an authenticated
`/reviews/{review_id}` graphical deep link; GET requests have no side effects; stale/double
resolution is rejected idempotently; allowed choices and typed overrides are server-validated; and
no raw body, unnecessary PII, checkpoint state or decrypted secure URL appears in Review HTML or
persisted Brief audit state.
