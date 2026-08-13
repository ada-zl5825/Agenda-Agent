"""CLI composition root for idempotently seeding the reviewed company catalog."""

import asyncio

from recruitment_agent.application.company_seed import CompanyCatalogSeeder
from recruitment_agent.config.settings import get_settings
from recruitment_agent.domain.company_seed import COMMON_COMPANY_SEEDS
from recruitment_agent.persistence.companies import SqlAlchemyCompanyRepository
from recruitment_agent.persistence.session import create_database_engine, create_session_factory


async def seed_common_companies() -> int:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    try:
        repository = SqlAlchemyCompanyRepository(create_session_factory(engine))
        result = await CompanyCatalogSeeder(repository).seed(COMMON_COMPANY_SEEDS)
        return result.processed
    finally:
        await engine.dispose()


def main() -> None:
    processed = asyncio.run(seed_common_companies())
    print(f"Seeded {processed} canonical companies.")


if __name__ == "__main__":
    main()
