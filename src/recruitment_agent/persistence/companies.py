"""PostgreSQL repository for canonical companies and exact-match evidence."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.domain.company import (
    Company,
    CompanyEntityType,
    CompanySeed,
    CompanyStatus,
    normalize_company_name,
)
from recruitment_agent.persistence.models import (
    CompanyAliasModel,
    CompanyDomainModel,
    CompanyModel,
)


class SqlAlchemyCompanyRepository:
    """Store reviewed company facts and expose only deterministic exact lookups."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, company_id: UUID) -> Company | None:
        async with self._session_factory() as session:
            model = await session.get(CompanyModel, company_id)
        return None if model is None else self._to_entity(model)

    async def find_by_normalized_canonical_name(
        self,
        normalized_name: str,
    ) -> Sequence[Company]:
        statement = select(CompanyModel).where(
            CompanyModel.normalized_canonical_name == normalized_name,
            CompanyModel.status == CompanyStatus.ACTIVE.value,
        )
        return await self._find(statement)

    async def find_by_normalized_alias(
        self,
        normalized_alias: str,
    ) -> Sequence[Company]:
        statement = (
            select(CompanyModel)
            .join(CompanyAliasModel, CompanyAliasModel.company_id == CompanyModel.id)
            .where(
                CompanyAliasModel.normalized_alias == normalized_alias,
                CompanyModel.status == CompanyStatus.ACTIVE.value,
            )
        )
        return await self._find(statement)

    async def find_by_domain(self, domain: str) -> Sequence[Company]:
        statement = (
            select(CompanyModel)
            .join(CompanyDomainModel, CompanyDomainModel.company_id == CompanyModel.id)
            .where(
                CompanyDomainModel.domain == domain,
                CompanyModel.status == CompanyStatus.ACTIVE.value,
            )
        )
        return await self._find(statement)

    async def upsert_seed(self, seed: CompanySeed) -> Company:
        async with self._session_factory.begin() as session:
            statement = insert(CompanyModel).values(
                id=seed.id,
                canonical_name=seed.canonical_name,
                normalized_canonical_name=normalize_company_name(seed.canonical_name),
                display_name=seed.display_name,
                entity_type=seed.entity_type.value,
                parent_company_id=seed.parent_company_id,
                status=seed.status.value,
            )
            excluded = statement.excluded
            model = await session.scalar(
                statement.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "canonical_name": excluded.canonical_name,
                        "normalized_canonical_name": excluded.normalized_canonical_name,
                        "display_name": excluded.display_name,
                        "entity_type": excluded.entity_type,
                        "parent_company_id": excluded.parent_company_id,
                        "status": excluded.status,
                        "updated_at": func.now(),
                    },
                ).returning(CompanyModel)
            )
            if model is None:
                raise RuntimeError("company seed could not be persisted")

            for alias in seed.aliases:
                alias_statement = insert(CompanyAliasModel).values(
                    company_id=model.id,
                    alias=alias.alias,
                    normalized_alias=alias.normalized_alias,
                    language=alias.language,
                    source=alias.source.value,
                    confidence=alias.confidence,
                )
                alias_excluded = alias_statement.excluded
                await session.execute(
                    alias_statement.on_conflict_do_update(
                        index_elements=["company_id", "normalized_alias"],
                        set_={
                            "alias": alias_excluded.alias,
                            "language": alias_excluded.language,
                            "source": alias_excluded.source,
                            "confidence": alias_excluded.confidence,
                        },
                    )
                )

            for domain in seed.domains:
                domain_statement = insert(CompanyDomainModel).values(
                    company_id=model.id,
                    domain=domain.domain,
                    source=domain.source.value,
                    confidence=domain.confidence,
                )
                domain_excluded = domain_statement.excluded
                await session.execute(
                    domain_statement.on_conflict_do_update(
                        index_elements=["company_id", "domain"],
                        set_={
                            "source": domain_excluded.source,
                            "confidence": domain_excluded.confidence,
                        },
                    )
                )
            return self._to_entity(model)

    async def _find(self, statement: Select[tuple[CompanyModel]]) -> tuple[Company, ...]:
        async with self._session_factory() as session:
            models = (await session.scalars(statement)).unique().all()
        return tuple(self._to_entity(model) for model in sorted(models, key=lambda item: item.id))

    @staticmethod
    def _to_entity(model: CompanyModel) -> Company:
        return Company(
            id=model.id,
            canonical_name=model.canonical_name,
            display_name=model.display_name,
            entity_type=CompanyEntityType(model.entity_type),
            parent_company_id=model.parent_company_id,
            status=CompanyStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
