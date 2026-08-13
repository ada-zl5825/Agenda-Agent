"""PostgreSQL checkpointer composition isolated from application domain storage."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import make_url

CHECKPOINT_SCHEMA = "agent_checkpoint"


def checkpoint_connection_string(database_url: str) -> str:
    """Use the locked checkpointer package against its isolated PostgreSQL schema."""
    url = make_url(database_url)
    if "options" in url.query:
        raise ValueError("DATABASE_URL must not define PostgreSQL connection options")
    checkpoint_url = url.set(drivername="postgresql").update_query_dict(
        {"options": f"-csearch_path={CHECKPOINT_SCHEMA}"}
    )
    return checkpoint_url.render_as_string(hide_password=False)


@asynccontextmanager
async def open_postgres_checkpointer(
    database_url: str,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open an async saver; Alembic owns initial checkpoint table creation."""
    connection_string = checkpoint_connection_string(database_url)
    async with AsyncPostgresSaver.from_conn_string(connection_string) as checkpointer:
        yield checkpointer
