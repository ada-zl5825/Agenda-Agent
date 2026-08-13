import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from testcontainers.community.postgres import PostgresContainer

from recruitment_agent.application.company_seed import CompanyCatalogSeeder
from recruitment_agent.domain.company import CompanyResolutionMethod, CompanyResolutionStatus
from recruitment_agent.domain.company_resolution import CompanyResolver
from recruitment_agent.domain.company_seed import BYTEDANCE_ID, COMMON_COMPANY_SEEDS, TIKTOK_ID
from recruitment_agent.persistence.companies import SqlAlchemyCompanyRepository
from recruitment_agent.persistence.models import (
    ApplicationModel,
    CompanyAliasModel,
    CompanyDomainModel,
    CompanyModel,
)
from recruitment_agent.persistence.session import create_database_engine, create_session_factory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 on a Docker-enabled host",
    ),
]


@pytest.mark.asyncio
async def test_company_repository_seed_and_exact_resolution_against_postgres() -> None:
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "20260812_0003")

        legacy_application_id = uuid4()
        legacy_engine = create_database_engine(database_url)
        legacy_session_factory = create_session_factory(legacy_engine)
        async with legacy_session_factory.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO app.applications "
                    "(id, company_name, company_normalized, status, version) "
                    "VALUES (:id, :company_name, :company_normalized, 'unknown', 1)"
                ),
                {
                    "id": legacy_application_id,
                    "company_name": "  Original Company Ltd.  ",
                    "company_normalized": "original company ltd.",
                },
            )
        await legacy_engine.dispose()

        command.upgrade(config, "head")

        engine = create_database_engine(database_url)
        session_factory = create_session_factory(engine)
        repository = SqlAlchemyCompanyRepository(session_factory)
        seeder = CompanyCatalogSeeder(repository)

        first = await seeder.seed(COMMON_COMPANY_SEEDS)
        second = await seeder.seed(COMMON_COMPANY_SEEDS)
        resolver = CompanyResolver(repository)
        alias = await resolver.resolve(company_raw="字节跳动", sender_domain=None)
        domain = await resolver.resolve(company_raw=None, sender_domain="jobs.bytedance.com")
        tiktok = await repository.get(TIKTOK_ID)

        async with session_factory() as session:
            company_count = await session.scalar(select(func.count()).select_from(CompanyModel))
            alias_count = await session.scalar(
                select(func.count()).select_from(CompanyAliasModel)
            )
            domain_count = await session.scalar(
                select(func.count()).select_from(CompanyDomainModel)
            )
            migrated_application = await session.get(ApplicationModel, legacy_application_id)
        await engine.dispose()

    assert first.company_ids == second.company_ids
    assert company_count == len(COMMON_COMPANY_SEEDS)
    assert alias_count == sum(len(seed.aliases) for seed in COMMON_COMPANY_SEEDS)
    assert domain_count == sum(len(seed.domains) for seed in COMMON_COMPANY_SEEDS)
    assert migrated_application is not None
    assert migrated_application.raw_company_name == "  Original Company Ltd.  "
    assert migrated_application.company_id is None
    assert alias.status is CompanyResolutionStatus.RESOLVED
    assert alias.method is CompanyResolutionMethod.ALIAS
    assert alias.company is not None
    assert alias.company.id == BYTEDANCE_ID
    assert domain.company is not None
    assert domain.company.id == BYTEDANCE_ID
    assert tiktok is not None
    assert tiktok.parent_company_id == BYTEDANCE_ID
