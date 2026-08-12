# Phase 0 Domain Model

`Application` is the aggregate root. `RecruitmentEvent` and `ActionItem` belong to an application and use explicit status enums. Normalized datetimes must be timezone-aware; an absent timezone is represented as unresolved evidence and must not be converted to a normalized datetime.

Repository protocols live in the domain package. SQLAlchemy models implement persistence concerns separately and never leak into domain types.

Phase 0 defines the stable vocabulary and boundaries only. State-transition, matching, rescheduling, deduplication and history services are implemented in later phases with deterministic tests.
