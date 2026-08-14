"""Unit tests for the allowlisted database-maintenance job entrypoint."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from recruitment_agent.jobs import database_maintenance


@pytest.fixture(autouse=True)
def _database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://example.invalid/recruitment")


def test_check_is_read_only_and_does_not_take_mutation_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock()
    lock = Mock()
    monkeypatch.setattr(database_maintenance.subprocess, "run", run)
    monkeypatch.setattr(database_maintenance, "_maintenance_lock", lock)

    database_maintenance.run_database_maintenance("check")

    lock.assert_not_called()
    run.assert_called_once_with(
        (
            database_maintenance.sys.executable,
            "-m",
            "alembic",
            "current",
            "--check-heads",
        ),
        check=True,
        timeout=300,
    )


@pytest.mark.parametrize(
    ("operation", "expected_tail"),
    [
        ("migrate", ("-m", "alembic", "upgrade", "head")),
        ("seed-companies", ("-m", "recruitment_agent.jobs.company_seed")),
    ],
)
def test_mutations_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
    operation: database_maintenance.MaintenanceOperation,
    expected_tail: tuple[str, ...],
) -> None:
    events: list[str] = []

    @contextmanager
    def lock() -> Iterator[None]:
        events.append("lock")
        yield
        events.append("unlock")

    def run(command: tuple[str, ...], *, check: bool, timeout: int) -> None:
        assert check is True
        assert timeout == 1_500
        assert command[1:] == expected_tail
        events.append("run")

    monkeypatch.setattr(database_maintenance, "_maintenance_lock", lock)
    monkeypatch.setattr(database_maintenance.subprocess, "run", run)

    database_maintenance.run_database_maintenance(operation)

    assert events == ["lock", "run", "unlock"]


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        database_maintenance.run_database_maintenance("check")


def test_parser_rejects_arbitrary_commands() -> None:
    with pytest.raises(SystemExit):
        database_maintenance._parse_operation(["psql", "-c", "DROP TABLE app.source_emails"])
