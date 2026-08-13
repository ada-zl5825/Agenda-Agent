"""PostgreSQL audit adapter for deterministic company resolution attempts."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruitment_agent.domain.company import CompanyResolutionAudit
from recruitment_agent.persistence.models import (
    CompanyResolutionAttemptModel,
    CompanyResolutionCandidateModel,
)


class SqlAlchemyCompanyResolutionAuditRepository:
    """Append a stable resolution attempt once, even when processing is retried."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, audit: CompanyResolutionAudit) -> None:
        resolution = audit.resolution
        role = audit.role
        async with self._session_factory.begin() as session:
            statement = insert(CompanyResolutionAttemptModel).values(
                id=audit.id,
                source_email_id=audit.source_email_id,
                sender_domain=audit.sender_domain,
                raw_company_name=resolution.raw_company_name,
                company_id=resolution.company_id,
                status=resolution.status.value,
                method=resolution.method.value,
                confidence=resolution.confidence,
                matched_value=resolution.matched_value,
                role_raw=role.raw_name,
                role_normalized=role.normalized_name,
                role_family=None if role.family is None else role.family.value,
            )
            await session.execute(statement.on_conflict_do_nothing(index_elements=["id"]))

            if resolution.candidate_company_ids:
                candidates = insert(CompanyResolutionCandidateModel).values(
                    [
                        {
                            "resolution_attempt_id": audit.id,
                            "company_id": company_id,
                        }
                        for company_id in resolution.candidate_company_ids
                    ]
                )
                await session.execute(
                    candidates.on_conflict_do_nothing(
                        index_elements=["resolution_attempt_id", "company_id"]
                    )
                )
