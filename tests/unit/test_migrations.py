from alembic import command
from alembic.config import Config


def test_full_migration_chain_compiles_for_postgresql() -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)


def test_phase_five_downgrade_compiles_for_postgresql() -> None:
    command.downgrade(
        Config("alembic.ini"),
        "20260813_0006:20260813_0005",
        sql=True,
    )


def test_phase_six_downgrade_compiles_for_postgresql() -> None:
    command.downgrade(
        Config("alembic.ini"),
        "20260813_0007:20260813_0006",
        sql=True,
    )


def test_phase_seven_downgrade_compiles_for_postgresql() -> None:
    command.downgrade(
        Config("alembic.ini"),
        "20260813_0008:20260813_0007",
        sql=True,
    )


def test_phase_eight_downgrade_compiles_for_postgresql() -> None:
    command.downgrade(
        Config("alembic.ini"),
        "20260813_0009:20260813_0008",
        sql=True,
    )
