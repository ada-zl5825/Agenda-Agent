# Test Plan through Phase 2

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
- deterministic repeated preparation and the attachment-download prohibition.

The Docker-backed PostgreSQL migration/upsert test runs when `RUN_POSTGRES_INTEGRATION=1`.
Phase 3 will add secure-link classification, encryption, repository, and link privacy tests.
