# Domain Model

`Application` remains the recruitment aggregate root. `RecruitmentEvent` and `ActionItem` belong to
an application and use explicit status enums. Email and future model output are evidence, not domain
state.

## Canonical company identity

Phase 3.5 introduces three domain-owned records:

- `Company`: canonical/display names, entity type, optional parent, lifecycle status, timestamps;
- `CompanyAlias`: original alias, deterministic normalized alias, optional language, reviewed source
  and confidence; and
- `CompanyDomain`: exact normalized sender hostname, reviewed source and confidence.

Parent references support brands, subsidiaries and parent organizations without flattening them into
one string. Company records are deactivated rather than silently remapped.

`Application.company_id` is the only canonical company identity. The source string is retained
unchanged as `Application.raw_company_name`; the former normalized company-name identity columns no
longer exist. Existing application rows migrate their old `company_name` into `raw_company_name` and
remain unresolved until a deterministic resolver or later review assigns `company_id`.

## Deterministic resolution

`CompanyResolver` gathers exact evidence from the domain-owned `CompanyRepository` using:

1. normalized canonical-name exact match;
2. normalized alias exact match;
3. normalized sender-domain exact match, skipping consumer mailboxes such as `126.com`,
   `163.com`, `qq.com`, `gmail.com`, and `outlook.com`.

One consistent active company returns `RESOLVED`. No match returns `UNRESOLVED`. Multiple exact
matches, including a company-name match that conflicts with the sender-domain match, return
`AMBIGUOUS` with candidate IDs. A matching name remains the reported method when name and domain
corroborate the same company. The resolver does not use substring matching, edit distance,
embeddings, external lookups or an LLM, and no evidence source silently overrides a conflict.

Every result preserves `raw_company_name` and reports `status`, `method`, `company_id`,
`confidence`, `matched_value` and any ambiguous candidate IDs. Phase 4.5 persists that result in an
append-only `company_resolution_attempts` record; ambiguous candidates are stored separately in
`company_resolution_candidates`. The attempt ID is derived from the complete deterministic
outcome, so a retry of the same source email and evidence is idempotent while a changed reviewed
catalog result remains a new auditable attempt.

An unresolved value is evidence, not a request to create a company. The original string remains in
`raw_company_name`, `company_id` remains null, and no catalog row is inserted. Adding a reviewed
company, alias or domain later makes future explicit resolution attempts eligible to match; it does
not silently backfill previously unresolved applications. A later review workflow must explicitly
request any re-resolution and application identity change.

The company-name normalizer applies Unicode NFKC, case folding, punctuation/symbol separation and
whitespace collapse only. It intentionally does not remove legal suffixes or infer corporate
relationships; reviewed aliases represent those variants explicitly.

## Phase 4 to Phase 4.5 boundary

`RawCompanyRole` prepares the provider-neutral contract:

```text
company_raw: str | None
role_raw: str | None
```

Both strings remain exactly as extracted. The Phase 4 model emits only this evidence; it cannot
choose a canonical company, write `company_id`, or mutate application state. The Phase 4.5
`RecruitmentEntityResolutionService` accepts only non-`INVALID`, relevant extraction outcomes,
invokes deterministic resolution and records its audit. A `NEEDS_REVIEW` extraction may still have
its deterministic entity evidence audited, but it does not authorize later domain mutations.

Phase 4.5 also produces a lightweight `NormalizedRole`: unchanged `raw_name`, deterministic
NFKC/case/punctuation-normalized `normalized_name`, and a coarse `RoleFamily`. This is support
evidence only. It does not create or select an `Application`, and Phase 4.5 performs no application,
calendar, email or secure-link mutation.

Repository protocols live in the domain package. SQLAlchemy models and seed execution are separate
persistence/composition concerns and never leak into the domain contracts.

## Phase 6 domain processing

LangGraph state remains execution state rather than a domain aggregate. PostgreSQL applications,
events, actions, and append-only histories are the source of truth. Phase 6 adds a provider-neutral
service that turns validated evidence into a checkpoint-safe intent and asks one atomic persistence
port to revalidate and apply it.

Application resolution first honors an existing source-email link, then uses canonical
`company_id` plus deterministically normalized role. One open match is selected, no match plans a
new application, and multiple matches interrupt with `APPLICATION_AMBIGUITY`. Missing roles use all
open applications for the canonical company and therefore review rather than silently creating a
duplicate. Unresolved companies require an explicit create-new review decision; they never create a
canonical company row.

Semantic event fingerprints contain canonical company identity, normalized role, event type,
round, normalized event time, and deadline. Fingerprint reuse applies only when the compared times
are actually resolved; two undated interviews do not collapse into one event. Replaying either the
same email or equivalent dated evidence reuses the existing event and action-item keys. A
reschedule searches active interview events, updates the one deterministic same-round target in
place, and records its previous time/status in `event_history`. A new `interview` whose only
same-round active interview has a different resolved time is treated as `interview_time_changed`
and follows the same in-place update. Zero or multiple plausible targets interrupt with
`UNCERTAIN_RESCHEDULE`.

Application transitions are monotonic for ordinary progress, preserve withdrawn applications, and
do not let assessment/interview evidence downgrade offer or rejection states. Every actual status
change records `application_status_history`. Assessment/interview actions keep only an encrypted
`secure_link_id`; graph state and transition plans contain the opaque link reference. Evidence with
an unresolved required datetime or timezone produces a zero-mutation plan. A named
wall-clock without a timezone is extracted; only the timezone waits for review.

## Phase 7 Calendar synchronization

`RecruitmentEvent` remains the source of truth. `calendar_links` stores only the provider mapping,
account identity, SHA-256 content fingerprint and last-sync timestamp. A unique constraint permits
at most one linked Calendar event per recruitment event; another unique constraint prevents one
provider event from being linked to two domain events.

The provider-neutral planner accepts only an active interview/reschedule with a confirmed start, or
an active assessment/deadline with a confirmed deadline. The application must have a canonical
company and the datetime must be timezone-aware with an explicitly resolved timezone. Unsupported
events are skipped; ambiguous or unsafe cases enter `UNSAFE_CALENDAR_UPDATE` Review. Reschedules
update the same linked Calendar event rather than creating another event.

Calendar duration is explicitly a configurable placeholder (60 minutes for interviews, 30 minutes
at assessment deadlines by default), never an inferred assessment or interview duration.

## Phase 8 and 9A (read models, not new aggregates)

Daily Brief and the Agent console do not introduce a second recruitment aggregate. They read
`Application`, `RecruitmentEvent`, `ActionItem`, and `review_items`, then render or send. Brief
dispatch is claimed at most once per account and local date. Operation runs and runtime controls
are operational state; they must not become a second source of truth for application status.
