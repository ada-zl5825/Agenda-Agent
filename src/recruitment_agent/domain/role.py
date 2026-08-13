"""Lightweight deterministic role normalization for resolution support only."""

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from recruitment_agent.domain.errors import DomainValidationError


class RoleFamily(StrEnum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    FULLSTACK = "fullstack"
    SOFTWARE_ENGINEERING = "software_engineering"
    MACHINE_LEARNING = "machine_learning"
    ALGORITHM = "algorithm"
    DATA = "data"
    INFRA = "infra"
    SECURITY = "security"
    PRODUCT = "product"
    OTHER = "other"
    UNKNOWN = "unknown"


def normalize_role_name(value: str) -> str:
    """Normalize a role label without turning it into application identity."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters = (
        " " if unicodedata.category(character)[0] in {"P", "S", "Z"} else character
        for character in normalized
    )
    return " ".join("".join(characters).split())


_FAMILY_KEYWORDS: tuple[tuple[RoleFamily, tuple[str, ...]], ...] = (
    (RoleFamily.MACHINE_LEARNING, ("machine learning", "ml engineer", "机器学习")),
    (RoleFamily.ALGORITHM, ("algorithm", "算法")),
    (RoleFamily.FULLSTACK, ("full stack", "fullstack", "全栈")),
    (RoleFamily.BACKEND, ("backend", "back end", "后端", "后台开发", "服务端")),
    (RoleFamily.FRONTEND, ("frontend", "front end", "前端")),
    (RoleFamily.SECURITY, ("security", "cyber", "安全")),
    (
        RoleFamily.INFRA,
        ("infrastructure", "platform engineer", "devops", "sre", "基础设施"),
    ),
    (RoleFamily.DATA, ("data", "数据")),
    (RoleFamily.PRODUCT, ("product manager", "product owner", "产品")),
    (
        RoleFamily.SOFTWARE_ENGINEERING,
        (
            "software engineer",
            "software developer",
            "graduate engineer",
            "开发工程师",
            "研发工程师",
            "软件工程师",
        ),
    ),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class NormalizedRole:
    raw_name: str | None
    normalized_name: str | None
    family: RoleFamily | None

    def __post_init__(self) -> None:
        if self.raw_name is None:
            if self.normalized_name is not None or self.family is not None:
                raise DomainValidationError("missing role cannot have normalized values")
            return
        if not self.raw_name.strip():
            raise DomainValidationError("raw role name must be null or non-empty")
        expected = normalize_role_name(self.raw_name)
        if self.normalized_name != expected or self.family is None:
            raise DomainValidationError("normalized role is inconsistent")


class RoleNormalizer:
    """Classify an auxiliary role family while preserving the exact source label."""

    def normalize(self, raw_name: str | None) -> NormalizedRole:
        if raw_name is None:
            return NormalizedRole(raw_name=None, normalized_name=None, family=None)

        normalized_name = normalize_role_name(raw_name)
        if not normalized_name:
            raise DomainValidationError("raw role name must be null or non-empty")
        family = next(
            (
                candidate
                for candidate, keywords in _FAMILY_KEYWORDS
                if any(keyword in normalized_name for keyword in keywords)
            ),
            RoleFamily.OTHER,
        )
        return NormalizedRole(
            raw_name=raw_name,
            normalized_name=normalized_name,
            family=family,
        )
