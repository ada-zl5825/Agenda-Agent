# Phase 0 Test Plan

The foundation test suite covers:

- domain entity invariants and timezone-aware normalized datetimes;
- typed settings validation;
- FastAPI health response;
- repository protocol shape;
- SQLAlchemy metadata, schemas, keys and uniqueness constraints;
- Alembic migration import and revision metadata.

PostgreSQL container integration tests will be added with the first persistence use case. Later phases add Graph contracts, email fixtures, privacy regressions, LangGraph branches and E2E acceptance tests from the final technical design.
