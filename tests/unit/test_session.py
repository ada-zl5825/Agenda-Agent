import pytest

from recruitment_agent.persistence.session import create_database_engine, create_session_factory


@pytest.mark.asyncio
async def test_session_factory_is_lazy() -> None:
    engine = create_database_engine(
        "postgresql+psycopg://user:password@localhost/recruitment",
    )
    factory = create_session_factory(engine)

    assert engine.url.drivername == "postgresql+psycopg"
    assert factory.kw["expire_on_commit"] is False

    await engine.dispose()
