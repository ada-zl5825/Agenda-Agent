"""Deterministic exact-match company resolution with conflict detection."""

from collections.abc import Sequence
from uuid import UUID

from recruitment_agent.domain.company import (
    CompanyResolution,
    CompanyResolutionMatch,
    CompanyResolutionMethod,
    CompanyResolutionStatus,
    normalize_company_domain,
    normalize_company_name,
)
from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.repositories import CompanyRepository


class CompanyResolver:
    """Resolve reviewed exact evidence and reject conflicting identities."""

    def __init__(self, repository: CompanyRepository) -> None:
        self._repository = repository

    async def resolve(
        self,
        *,
        company_raw: str | None,
        sender_domain: str | None,
    ) -> CompanyResolution:
        name_matches: tuple[CompanyResolutionMatch, ...] = ()
        name_method: CompanyResolutionMethod | None = None
        normalized_name = normalize_company_name(company_raw or "")
        if normalized_name:
            canonical = await self._repository.find_by_normalized_canonical_name(
                normalized_name
            )
            if canonical:
                name_matches = self._unique(canonical)
                name_method = CompanyResolutionMethod.CANONICAL_EXACT
            else:
                aliases = await self._repository.find_by_normalized_alias(normalized_name)
                if aliases:
                    name_matches = self._unique(aliases)
                    name_method = CompanyResolutionMethod.ALIAS_EXACT

        domain_matches: tuple[CompanyResolutionMatch, ...] = ()
        if sender_domain is not None:
            try:
                normalized_domain = normalize_company_domain(sender_domain)
            except DomainValidationError:
                normalized_domain = None
            if normalized_domain is not None:
                domain_matches = self._unique(
                    await self._repository.find_by_domain(normalized_domain)
                )

        candidate_ids = {
            match.company_id for match in (*name_matches, *domain_matches)
        }
        if len(name_matches) > 1 or len(domain_matches) > 1 or len(candidate_ids) > 1:
            return CompanyResolution(
                raw_company_name=company_raw,
                status=CompanyResolutionStatus.AMBIGUOUS,
                method=CompanyResolutionMethod.AMBIGUOUS,
                company_id=None,
                confidence=0.0,
                matched_value=None,
                candidate_company_ids=tuple(sorted(candidate_ids)),
            )

        if name_matches:
            match = name_matches[0]
            if name_method is None:
                raise RuntimeError("name match must have a deterministic method")
            return self._resolved(company_raw, match=match, method=name_method)
        if domain_matches:
            return self._resolved(
                company_raw,
                match=domain_matches[0],
                method=CompanyResolutionMethod.DOMAIN_EXACT,
            )
        return CompanyResolution(
            raw_company_name=company_raw,
            status=CompanyResolutionStatus.UNRESOLVED,
            method=CompanyResolutionMethod.UNRESOLVED,
            company_id=None,
            confidence=0.0,
            matched_value=None,
        )

    @staticmethod
    def _resolved(
        raw_company_name: str | None,
        *,
        match: CompanyResolutionMatch,
        method: CompanyResolutionMethod,
    ) -> CompanyResolution:
        return CompanyResolution(
            raw_company_name=raw_company_name,
            status=CompanyResolutionStatus.RESOLVED,
            method=method,
            company_id=match.company_id,
            confidence=match.confidence,
            matched_value=match.matched_value,
        )

    @staticmethod
    def _unique(
        matches: Sequence[CompanyResolutionMatch],
    ) -> tuple[CompanyResolutionMatch, ...]:
        by_company: dict[UUID, CompanyResolutionMatch] = {}
        for match in matches:
            current = by_company.get(match.company_id)
            if current is None or match.confidence > current.confidence:
                by_company[match.company_id] = match
        return tuple(by_company[key] for key in sorted(by_company))
