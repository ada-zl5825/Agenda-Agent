"""Allowlisted entrypoint for the private database-maintenance Container Apps Job."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Final, Literal, cast

import psycopg

type MaintenanceOperation = Literal["check", "migrate", "seed-companies"]

_OPERATIONS: Final[tuple[MaintenanceOperation, ...]] = (
    "check",
    "migrate",
    "seed-companies",
)
_ALEMBIC_LOCK_ID: Final = 7_094_302_722_602_024


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for database maintenance")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _maintenance_lock() -> Iterator[None]:
    """Serialize schema/catalog mutations across independently started executions."""
    with psycopg.connect(_database_url(), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (_ALEMBIC_LOCK_ID,))
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (_ALEMBIC_LOCK_ID,))


def _command_for(operation: MaintenanceOperation) -> tuple[str, ...]:
    if operation == "check":
        return (sys.executable, "-m", "alembic", "current", "--check-heads")
    if operation == "migrate":
        return (sys.executable, "-m", "alembic", "upgrade", "head")
    return (sys.executable, "-m", "recruitment_agent.jobs.company_seed")


def run_database_maintenance(operation: MaintenanceOperation) -> None:
    """Run exactly one validated operation without invoking a shell."""
    _database_url()
    command = _command_for(operation)
    if operation == "check":
        subprocess.run(command, check=True, timeout=300)
        return

    with _maintenance_lock():
        subprocess.run(command, check=True, timeout=1_500)


def _parse_operation(argv: Sequence[str] | None = None) -> MaintenanceOperation:
    parser = argparse.ArgumentParser(description="Run an allowlisted database operation.")
    parser.add_argument("operation", choices=_OPERATIONS, nargs="?", default="check")
    arguments = parser.parse_args(argv)
    return cast(MaintenanceOperation, arguments.operation)


def main(argv: Sequence[str] | None = None) -> None:
    operation = _parse_operation(argv)
    print(f"Starting database maintenance operation: {operation}")
    run_database_maintenance(operation)
    print(f"Database maintenance operation succeeded: {operation}")


if __name__ == "__main__":
    main()
