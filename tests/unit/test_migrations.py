from alembic import command
from alembic.config import Config


def test_full_migration_chain_compiles_for_postgresql() -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)


def test_phase_three_five_downgrade_compiles_for_postgresql() -> None:
    command.downgrade(
        Config("alembic.ini"),
        "20260813_0004:20260812_0003",
        sql=True,
    )
