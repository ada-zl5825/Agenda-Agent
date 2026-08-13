"""Canonical company entities and deterministic normalization contracts."""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5

from recruitment_agent.domain.errors import DomainValidationError
from recruitment_agent.domain.role import NormalizedRole
from recruitment_agent.domain.time import require_aware


class CompanyEntityType(StrEnum):
    EMPLOYER = "employer"
    PARENT = "parent"
    SUBSIDIARY = "subsidiary"
    BRAND = "brand"
    RECRUITMENT_AGENCY = "recruitment_agency"


class CompanyStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class CompanyDataSource(StrEnum):
    SEED = "seed"
    MANUAL = "manual"
    OBSERVED = "observed"


class CompanyResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


class CompanyResolutionMethod(StrEnum):
    CANONICAL_EXACT = "canonical_exact"
    ALIAS_EXACT = "alias_exact"
    DOMAIN_EXACT = "domain_exact"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


def normalize_company_name(value: str) -> str:
    """Normalize Unicode, case, punctuation, and whitespace without fuzzy matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters = (
        " " if unicodedata.category(character)[0] in {"P", "S", "Z"} else character
        for character in normalized
    )
    return " ".join("".join(characters).split())


_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_company_domain(value: str) -> str:
    """Return an ASCII lower-case hostname suitable for exact matching."""
    candidate = unicodedata.normalize("NFKC", value).strip().casefold().rstrip(".")
    if not candidate or "://" in candidate or any(mark in candidate for mark in "/@?#"):
        raise DomainValidationError("company domain must be a bare hostname")
    try:
        ascii_domain = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DomainValidationError("company domain is invalid") from exc
    labels = ascii_domain.split(".")
    if len(labels) < 2 or any(_DOMAIN_LABEL.fullmatch(label) is None for label in labels):
        raise DomainValidationError("company domain is invalid")
    return ascii_domain


def _required_text(value: str, *, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise DomainValidationError(f"{field_name} must not be empty")
    return stripped


def _validate_confidence(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise DomainValidationError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True, kw_only=True)
class Company:
    id: UUID
    canonical_name: str
    display_name: str
    entity_type: CompanyEntityType
    parent_company_id: UUID | None
    status: CompanyStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_name",
            _required_text(self.canonical_name, field_name="canonical_name"),
        )
        object.__setattr__(
            self,
            "display_name",
            _required_text(self.display_name, field_name="display_name"),
        )
        if self.parent_company_id == self.id:
            raise DomainValidationError("company cannot be its own parent")
        require_aware(self.created_at, field_name="created_at")
        require_aware(self.updated_at, field_name="updated_at")
        if self.updated_at < self.created_at:
            raise DomainValidationError("updated_at must not precede created_at")

    @property
    def normalized_canonical_name(self) -> str:
        return normalize_company_name(self.canonical_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyAlias:
    company_id: UUID
    alias: str
    normalized_alias: str
    language: str | None
    source: CompanyDataSource
    confidence: float

    def __post_init__(self) -> None:
        alias = _required_text(self.alias, field_name="alias")
        object.__setattr__(self, "alias", alias)
        expected = normalize_company_name(alias)
        if not expected or self.normalized_alias != expected:
            raise DomainValidationError("normalized_alias must match deterministic normalization")
        if self.language is not None:
            language = self.language.strip()
            object.__setattr__(self, "language", language or None)
        _validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyDomain:
    company_id: UUID
    domain: str
    source: CompanyDataSource
    confidence: float

    def __post_init__(self) -> None:
        normalized = normalize_company_domain(self.domain)
        if self.domain != normalized:
            raise DomainValidationError(
                "domain must be normalized before constructing CompanyDomain"
            )
        _validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyAliasSeed:
    alias: str
    language: str | None = None
    source: CompanyDataSource = CompanyDataSource.SEED
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _required_text(self.alias, field_name="alias")
        _validate_confidence(self.confidence)

    @property
    def normalized_alias(self) -> str:
        return normalize_company_name(self.alias)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyDomainSeed:
    domain: str
    source: CompanyDataSource = CompanyDataSource.SEED
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain", normalize_company_domain(self.domain))
        _validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanySeed:
    id: UUID
    canonical_name: str
    display_name: str
    entity_type: CompanyEntityType
    parent_company_id: UUID | None = None
    status: CompanyStatus = CompanyStatus.ACTIVE
    aliases: tuple[CompanyAliasSeed, ...] = ()
    domains: tuple[CompanyDomainSeed, ...] = ()

    def __post_init__(self) -> None:
        _required_text(self.canonical_name, field_name="canonical_name")
        _required_text(self.display_name, field_name="display_name")
        if self.parent_company_id == self.id:
            raise DomainValidationError("company seed cannot be its own parent")


@dataclass(frozen=True, slots=True, kw_only=True)
class RawCompanyRole:
    """Unresolved Phase 4 evidence; values remain exactly as emitted by extraction."""

    company_raw: str | None
    role_raw: str | None

    def __post_init__(self) -> None:
        if self.company_raw is not None and not self.company_raw.strip():
            raise DomainValidationError("company_raw must be null or non-empty")
        if self.role_raw is not None and not self.role_raw.strip():
            raise DomainValidationError("role_raw must be null or non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyResolutionMatch:
    company_id: UUID
    matched_value: str
    confidence: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "matched_value",
            _required_text(self.matched_value, field_name="matched_value"),
        )
        _validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyResolution:
    raw_company_name: str | None
    status: CompanyResolutionStatus
    method: CompanyResolutionMethod
    company_id: UUID | None
    confidence: float
    matched_value: str | None
    candidate_company_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if self.raw_company_name is not None and not self.raw_company_name.strip():
            raise DomainValidationError("raw_company_name must be null or non-empty")
        _validate_confidence(self.confidence)
        if self.matched_value is not None:
            object.__setattr__(
                self,
                "matched_value",
                _required_text(self.matched_value, field_name="matched_value"),
            )
        if len(self.candidate_company_ids) != len(set(self.candidate_company_ids)):
            raise DomainValidationError("candidate company IDs must be unique")
        object.__setattr__(self, "candidate_company_ids", tuple(sorted(self.candidate_company_ids)))

        if self.status is CompanyResolutionStatus.RESOLVED:
            exact_methods = {
                CompanyResolutionMethod.CANONICAL_EXACT,
                CompanyResolutionMethod.ALIAS_EXACT,
                CompanyResolutionMethod.DOMAIN_EXACT,
            }
            if (
                self.company_id is None
                or self.method not in exact_methods
                or self.matched_value is None
                or self.candidate_company_ids
            ):
                raise DomainValidationError("resolved company result is inconsistent")
        elif self.status is CompanyResolutionStatus.AMBIGUOUS:
            if (
                self.company_id is not None
                or self.method is not CompanyResolutionMethod.AMBIGUOUS
                or self.confidence != 0.0
                or self.matched_value is not None
            ):
                raise DomainValidationError("ambiguous company result is inconsistent")
            if len(self.candidate_company_ids) < 2:
                raise DomainValidationError("ambiguous result requires at least two candidates")
        elif (
            self.company_id is not None
            or self.method is not CompanyResolutionMethod.UNRESOLVED
            or self.confidence != 0.0
            or self.matched_value is not None
            or self.candidate_company_ids
        ):
            raise DomainValidationError("unresolved company result cannot contain a match")


CompanyResolutionResult = CompanyResolution


_COMPANY_RESOLUTION_AUDIT_NAMESPACE = UUID("c7757331-a2c0-45db-a79a-9cdb2bd2d83a")


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyResolutionAudit:
    """Idempotent audit record for one deterministic resolution outcome."""

    id: UUID
    source_email_id: UUID
    sender_domain: str | None
    resolution: CompanyResolution
    role: NormalizedRole

    @classmethod
    def create(
        cls,
        *,
        source_email_id: UUID,
        sender_domain: str | None,
        resolution: CompanyResolution,
        role: NormalizedRole,
    ) -> "CompanyResolutionAudit":
        payload = json.dumps(
            {
                "source_email_id": str(source_email_id),
                "sender_domain": sender_domain,
                "raw_company_name": resolution.raw_company_name,
                "company_id": None
                if resolution.company_id is None
                else str(resolution.company_id),
                "status": resolution.status.value,
                "method": resolution.method.value,
                "confidence": resolution.confidence,
                "matched_value": resolution.matched_value,
                "candidate_company_ids": [
                    str(company_id) for company_id in resolution.candidate_company_ids
                ],
                "role_raw": role.raw_name,
                "role_normalized": role.normalized_name,
                "role_family": None if role.family is None else role.family.value,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return cls(
            id=uuid5(_COMPANY_RESOLUTION_AUDIT_NAMESPACE, payload),
            source_email_id=source_email_id,
            sender_domain=sender_domain,
            resolution=resolution,
            role=role,
        )
