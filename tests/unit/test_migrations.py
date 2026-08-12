from alembic import command
from alembic.config import Config


def test_full_migration_chain_compiles_for_postgresql() -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
