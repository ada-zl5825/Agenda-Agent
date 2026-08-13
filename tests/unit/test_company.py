from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from recruitment_agent.application.company_seed import CompanyCatalogSeeder
from recruitment_agent.domain.company import (
    Company,
    CompanyAlias,
    CompanyAliasSeed,
    CompanyDataSource,
    CompanyDomain,
    CompanyDomainSeed,
    CompanyEntityType,
    CompanyResolutionMatch,
    CompanyResolutionMethod,
    CompanyResolutionStatus,
    CompanySeed,
    CompanyStatus,
    RawCompanyRole,
    normalize_company_domain,
    normalize_company_name,
)
from recruitment_agent.domain.company_resolution import CompanyResolver
from recruitment_agent.domain.company_seed import (
    BYTEDANCE_ID,
    COMMON_COMPANY_SEEDS,
    TIKTOK_ID,
)
from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.role import RoleFamily, RoleNormalizer


def company(name: str, *, company_id: UUID | None = None) -> Company:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    return Company(
        id=company_id or uuid4(),
        canonical_name=name,
        display_name=name,
        entity_type=CompanyEntityType.EMPLOYER,
        parent_company_id=None,
        status=CompanyStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


class InMemoryCompanyRepository:
    def __init__(self) -> None:
        self.companies: dict[UUID, Company] = {}
        self.canonical: dict[str, list[CompanyResolutionMatch]] = {}
        self.aliases: dict[str, list[CompanyResolutionMatch]] = {}
        self.domains: dict[str, list[CompanyResolutionMatch]] = {}

    async def get(self, company_id: UUID) -> Company | None:
        return self.companies.get(company_id)

    async def find_by_normalized_canonical_name(
        self,
        normalized_name: str,
    ) -> tuple[CompanyResolutionMatch, ...]:
        return tuple(self.canonical.get(normalized_name, ()))

    async def find_by_normalized_alias(
        self,
        normalized_alias: str,
    ) -> tuple[CompanyResolutionMatch, ...]:
        return tuple(self.aliases.get(normalized_alias, ()))

    async def find_by_domain(self, domain: str) -> tuple[CompanyResolutionMatch, ...]:
        return tuple(self.domains.get(domain, ()))

    async def upsert_seed(self, seed: CompanySeed) -> Company:
        existing = self.companies.get(seed.id)
        stored = existing or company(seed.canonical_name, company_id=seed.id)
        if existing is None:
            self.companies[stored.id] = stored
            self.canonical.setdefault(stored.normalized_canonical_name, []).append(
                CompanyResolutionMatch(
                    company_id=stored.id,
                    matched_value=stored.normalized_canonical_name,
                    confidence=1.0,
                )
            )
        for alias in seed.aliases:
            matches = self.aliases.setdefault(alias.normalized_alias, [])
            match = CompanyResolutionMatch(
                company_id=stored.id,
                matched_value=alias.normalized_alias,
                confidence=alias.confidence,
            )
            if match not in matches:
                matches.append(match)
        for domain in seed.domains:
            matches = self.domains.setdefault(domain.domain, [])
            match = CompanyResolutionMatch(
                company_id=stored.id,
                matched_value=domain.domain,
                confidence=domain.confidence,
            )
            if match not in matches:
                matches.append(match)
        return stored


def test_company_name_normalization_is_exact_and_not_fuzzy() -> None:
    full_width = "  \uff22\uff59\uff54\uff45\uff0d\uff24\uff41\uff4e\uff43\uff45, Inc. "
    assert normalize_company_name(full_width) == "byte dance inc"
    assert normalize_company_name("字节\u3000跳动") == "字节 跳动"
    assert normalize_company_name("Acme Ltd") != normalize_company_name("Acme")


def test_company_domain_normalization_requires_a_bare_hostname() -> None:
    assert normalize_company_domain(" Careers.Example.COM. ") == "careers.example.com"
    assert normalize_company_domain("招聘.公司.cn").endswith(".cn")

    with pytest.raises(DomainValidationError, match="bare hostname"):
        normalize_company_domain("https://careers.example.com/jobs")


def test_company_alias_domain_and_parent_invariants() -> None:
    company_id = uuid4()
    alias = CompanyAlias(
        company_id=company_id,
        alias="字节跳动",
        normalized_alias="字节跳动",
        language="zh",
        source=CompanyDataSource.MANUAL,
        confidence=0.9,
    )
    domain = CompanyDomain(
        company_id=company_id,
        domain="bytedance.com",
        source=CompanyDataSource.MANUAL,
        confidence=1.0,
    )

    assert alias.normalized_alias == normalize_company_name(alias.alias)
    assert domain.domain == "bytedance.com"

    with pytest.raises(DomainValidationError, match="own parent"):
        Company(
            id=company_id,
            canonical_name="Loop",
            display_name="Loop",
            entity_type=CompanyEntityType.SUBSIDIARY,
            parent_company_id=company_id,
            status=CompanyStatus.ACTIVE,
            created_at=datetime(2026, 8, 13, tzinfo=UTC),
            updated_at=datetime(2026, 8, 13, tzinfo=UTC),
        )


def test_raw_phase_four_contract_preserves_original_strings() -> None:
    evidence = RawCompanyRole(
        company_raw="  ByteDance 招聘  ",
        role_raw="  Backend Engineer  ",
    )

    assert evidence.company_raw == "  ByteDance 招聘  "
    assert evidence.role_raw == "  Backend Engineer  "


@pytest.mark.asyncio
async def test_resolver_uses_canonical_then_alias_then_domain_exact_matches() -> None:
    repository = InMemoryCompanyRepository()
    seeded = await CompanyCatalogSeeder(repository).seed(COMMON_COMPANY_SEEDS)
    resolver = CompanyResolver(repository)

    canonical = await resolver.resolve(company_raw="BYTEDANCE", sender_domain=None)
    alias = await resolver.resolve(company_raw="字节跳动", sender_domain=None)
    domain = await resolver.resolve(company_raw=None, sender_domain="JOBS.BYTEDANCE.COM.")

    assert seeded.processed == len(COMMON_COMPANY_SEEDS)
    assert canonical.status is CompanyResolutionStatus.RESOLVED
    assert canonical.method is CompanyResolutionMethod.CANONICAL_EXACT
    assert canonical.company_id == BYTEDANCE_ID
    assert canonical.matched_value == "bytedance"
    assert canonical.confidence == 1.0
    assert alias.method is CompanyResolutionMethod.ALIAS_EXACT
    assert alias.company_id == BYTEDANCE_ID
    assert domain.method is CompanyResolutionMethod.DOMAIN_EXACT
    assert domain.company_id == BYTEDANCE_ID


@pytest.mark.asyncio
async def test_resolver_leaves_unknown_and_fuzzy_names_unresolved() -> None:
    repository = InMemoryCompanyRepository()
    await CompanyCatalogSeeder(repository).seed(COMMON_COMPANY_SEEDS)
    resolver = CompanyResolver(repository)

    unknown = await resolver.resolve(company_raw="Unknown Labs", sender_domain=None)
    fuzzy = await resolver.resolve(company_raw="ByteDanc", sender_domain=None)
    invalid_domain = await resolver.resolve(company_raw=None, sender_domain="not a domain")

    assert unknown.status is CompanyResolutionStatus.UNRESOLVED
    assert unknown.method is CompanyResolutionMethod.UNRESOLVED
    assert unknown.raw_company_name == "Unknown Labs"
    assert unknown.confidence == 0.0
    assert fuzzy.status is CompanyResolutionStatus.UNRESOLVED
    assert invalid_domain.status is CompanyResolutionStatus.UNRESOLVED


@pytest.mark.asyncio
async def test_unknown_company_resolves_only_after_reviewed_seed_and_explicit_retry() -> None:
    repository = InMemoryCompanyRepository()
    resolver = CompanyResolver(repository)

    before_review = await resolver.resolve(
        company_raw="Acme Limited",
        sender_domain="careers.acme.example",
    )
    assert before_review.status is CompanyResolutionStatus.UNRESOLVED
    assert repository.companies == {}

    reviewed = CompanySeed(
        id=uuid4(),
        canonical_name="Acme",
        display_name="Acme",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(),
        domains=(),
    )
    await CompanyCatalogSeeder(repository).seed((reviewed,))
    still_unresolved = await resolver.resolve(
        company_raw="Acme Limited",
        sender_domain="careers.acme.example",
    )
    assert still_unresolved.status is CompanyResolutionStatus.UNRESOLVED

    reviewed_with_evidence = CompanySeed(
        id=reviewed.id,
        canonical_name="Acme",
        display_name="Acme",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="Acme Limited", language="en"),
        ),
        domains=(CompanyDomainSeed(domain="careers.acme.example"),),
    )
    await CompanyCatalogSeeder(repository).seed((reviewed_with_evidence,))
    after_review = await resolver.resolve(
        company_raw="Acme Limited",
        sender_domain="careers.acme.example",
    )

    assert after_review.status is CompanyResolutionStatus.RESOLVED
    assert after_review.method is CompanyResolutionMethod.ALIAS_EXACT
    assert after_review.company_id == reviewed.id


@pytest.mark.asyncio
async def test_resolver_returns_ambiguous_without_using_domain_to_guess() -> None:
    repository = InMemoryCompanyRepository()
    first = company("Example One")
    second = company("Example Two")
    repository.aliases["example"] = [
        CompanyResolutionMatch(
            company_id=first.id,
            matched_value="example",
            confidence=1.0,
        ),
        CompanyResolutionMatch(
            company_id=second.id,
            matched_value="example",
            confidence=1.0,
        ),
    ]
    repository.domains["one.example.com"] = [
        CompanyResolutionMatch(
            company_id=first.id,
            matched_value="one.example.com",
            confidence=1.0,
        )
    ]

    result = await CompanyResolver(repository).resolve(
        company_raw="Example",
        sender_domain="one.example.com",
    )

    assert result.status is CompanyResolutionStatus.AMBIGUOUS
    assert result.method is CompanyResolutionMethod.AMBIGUOUS
    assert result.company_id is None
    assert set(result.candidate_company_ids) == {first.id, second.id}


@pytest.mark.asyncio
async def test_resolver_marks_conflicting_name_and_domain_evidence_ambiguous() -> None:
    repository = InMemoryCompanyRepository()
    name_company = company("Tencent")
    domain_company = company("Alibaba")
    repository.aliases["tencent"] = [
        CompanyResolutionMatch(
            company_id=name_company.id,
            matched_value="tencent",
            confidence=0.95,
        )
    ]
    repository.domains["alibaba.com"] = [
        CompanyResolutionMatch(
            company_id=domain_company.id,
            matched_value="alibaba.com",
            confidence=1.0,
        )
    ]

    result = await CompanyResolver(repository).resolve(
        company_raw="Tencent",
        sender_domain="alibaba.com",
    )

    assert result.status is CompanyResolutionStatus.AMBIGUOUS
    assert set(result.candidate_company_ids) == {name_company.id, domain_company.id}


def test_role_normalizer_preserves_raw_name_and_classifies_lightweight_family() -> None:
    backend = RoleNormalizer().normalize("  Senior Backend Engineer  ")
    machine_learning = RoleNormalizer().normalize("机器学习算法工程师")
    unknown = RoleNormalizer().normalize("Chief Happiness Officer")
    missing = RoleNormalizer().normalize(None)

    assert backend.raw_name == "  Senior Backend Engineer  "
    assert backend.normalized_name == "senior backend engineer"
    assert backend.family is RoleFamily.BACKEND
    assert machine_learning.family is RoleFamily.MACHINE_LEARNING
    assert unknown.family is RoleFamily.OTHER
    assert missing.normalized_name is None
    assert missing.family is None


@pytest.mark.asyncio
async def test_common_seed_is_idempotent_and_orders_parent_before_child() -> None:
    repository = InMemoryCompanyRepository()
    seeder = CompanyCatalogSeeder(repository)

    first = await seeder.seed(COMMON_COMPANY_SEEDS)
    second = await seeder.seed(COMMON_COMPANY_SEEDS)

    assert first.company_ids == second.company_ids
    assert len(repository.companies) == len(COMMON_COMPANY_SEEDS)
    assert first.company_ids.index(BYTEDANCE_ID) < first.company_ids.index(TIKTOK_ID)
    tiktok_seed = next(seed for seed in COMMON_COMPANY_SEEDS if seed.id == TIKTOK_ID)
    assert tiktok_seed.parent_company_id == BYTEDANCE_ID


def test_expanded_common_seed_has_unique_exact_match_keys() -> None:
    assert len(COMMON_COMPANY_SEEDS) == 35
    assert len({seed.id for seed in COMMON_COMPANY_SEEDS}) == 35
    assert len(
        {normalize_company_name(seed.canonical_name) for seed in COMMON_COMPANY_SEEDS}
    ) == len(COMMON_COMPANY_SEEDS)

    domains = [domain.domain for seed in COMMON_COMPANY_SEEDS for domain in seed.domains]
    assert len(domains) == len(set(domains))

    alias_owners: dict[str, UUID] = {}
    for seed in COMMON_COMPANY_SEEDS:
        for alias in seed.aliases:
            owner = alias_owners.setdefault(alias.normalized_alias, seed.id)
            assert owner == seed.id
