"""Idempotent application service for the built-in company catalog."""

from dataclasses import dataclass
from uuid import UUID

from recruitment_agent.domain.company import CompanySeed
from recruitment_agent.domain.repositories import CompanyRepository


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanySeedResult:
    processed: int
    company_ids: tuple[UUID, ...]


class CompanyCatalogSeeder:
    def __init__(self, repository: CompanyRepository) -> None:
        self._repository = repository

    async def seed(self, entries: tuple[CompanySeed, ...]) -> CompanySeedResult:
        stored = tuple([await self._repository.upsert_seed(entry) for entry in entries])
        return CompanySeedResult(
            processed=len(stored),
            company_ids=tuple(company.id for company in stored),
        )
