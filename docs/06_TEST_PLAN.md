# Test Plan through Phase 3.5

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
- stable parent-child seed IDs and repeatable catalog seeding;
- `Application.company_id` identity with unchanged `raw_company_name` evidence; and
- Phase 3.5 migration preservation plus PostgreSQL repository lookups.

The Docker-backed PostgreSQL migration/upsert tests run when `RUN_POSTGRES_INTEGRATION=1`.
They cover Graph email metadata, encrypted secure-link persistence, company seed idempotency and
legacy application company-name migration.
