from recruitment_agent.graph.postgres import (
    CHECKPOINT_SCHEMA,
    checkpoint_connection_string,
)


def test_checkpoint_connection_uses_isolated_schema_and_psycopg_url() -> None:
    connection = checkpoint_connection_string(
        "postgresql+psycopg://user:password@localhost/recruitment?sslmode=require"
    )

    assert connection.startswith("postgresql://user:password@localhost/recruitment?")
    assert "sslmode=require" in connection
    assert "options=-csearch_path%3Dagent_checkpoint" in connection
    assert CHECKPOINT_SCHEMA == "agent_checkpoint"
