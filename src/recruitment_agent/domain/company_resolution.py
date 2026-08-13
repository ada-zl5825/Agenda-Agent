"""Deterministic exact-match company resolution."""

from collections.abc import Sequence

from recruitment_agent.domain.company import (
    Company,
    CompanyResolution,
    CompanyResolutionMethod,
    CompanyResolutionStatus,
    normalize_company_domain,
    normalize_company_name,
)
from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.repositories import CompanyRepository


class CompanyResolver:
    """Resolve canonical name, then alias, then sender domain; never guess."""

    def __init__(self, repository: CompanyRepository) -> None:
        self._repository = repository

    async def resolve(
        self,
        *,
        company_raw: str | None,
        sender_domain: str | None,
    ) -> CompanyResolution:
        normalized_name = normalize_company_name(company_raw or "")
        if normalized_name:
            canonical = await self._repository.find_by_normalized_canonical_name(
                normalized_name
            )
            result = self._from_matches(
                canonical,
                method=CompanyResolutionMethod.CANONICAL_NAME,
            )
            if result.status is not CompanyResolutionStatus.UNRESOLVED:
                return result

            aliases = await self._repository.find_by_normalized_alias(normalized_name)
            result = self._from_matches(aliases, method=CompanyResolutionMethod.ALIAS)
            if result.status is not CompanyResolutionStatus.UNRESOLVED:
                return result

        if sender_domain is not None:
            try:
                normalized_domain = normalize_company_domain(sender_domain)
            except DomainValidationError:
                normalized_domain = None
            if normalized_domain is not None:
                domains = await self._repository.find_by_domain(normalized_domain)
                result = self._from_matches(
                    domains,
                    method=CompanyResolutionMethod.SENDER_DOMAIN,
                )
                if result.status is not CompanyResolutionStatus.UNRESOLVED:
                    return result

        return CompanyResolution(
            status=CompanyResolutionStatus.UNRESOLVED,
            method=None,
            company=None,
        )

    @staticmethod
    def _from_matches(
        matches: Sequence[Company],
        *,
        method: CompanyResolutionMethod,
    ) -> CompanyResolution:
        unique = {company.id: company for company in matches}
        if len(unique) == 1:
            return CompanyResolution(
                status=CompanyResolutionStatus.RESOLVED,
                method=method,
                company=next(iter(unique.values())),
            )
        if len(unique) > 1:
            return CompanyResolution(
                status=CompanyResolutionStatus.AMBIGUOUS,
                method=method,
                company=None,
                candidate_company_ids=tuple(sorted(unique)),
            )
        return CompanyResolution(
            status=CompanyResolutionStatus.UNRESOLVED,
            method=None,
            company=None,
        )
