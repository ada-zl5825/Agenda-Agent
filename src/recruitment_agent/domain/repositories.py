"""Repository and transaction ports owned by the domain boundary."""

from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from recruitment_agent.domain.action import ActionItem
from recruitment_agent.domain.application import Application
from recruitment_agent.domain.company import (
    Company,
    CompanyResolutionAudit,
    CompanyResolutionMatch,
    CompanySeed,
)
from recruitment_agent.domain.event import RecruitmentEvent


class ApplicationRepository(Protocol):
    async def get(self, application_id: UUID) -> Application | None: ...

    async def add(self, application: Application) -> None: ...

    async def find_open_by_identity(
        self,
        *,
        company_id: UUID,
        role_name: str | None,
    ) -> Sequence[Application]: ...


class CompanyRepository(Protocol):
    async def get(self, company_id: UUID) -> Company | None: ...

    async def find_by_normalized_canonical_name(
        self,
        normalized_name: str,
    ) -> Sequence[CompanyResolutionMatch]: ...

    async def find_by_normalized_alias(
        self,
        normalized_alias: str,
    ) -> Sequence[CompanyResolutionMatch]: ...

    async def find_by_domain(self, domain: str) -> Sequence[CompanyResolutionMatch]: ...

    async def upsert_seed(self, seed: CompanySeed) -> Company: ...


class CompanyResolutionAuditRepository(Protocol):
    async def add(self, audit: CompanyResolutionAudit) -> None: ...


class RecruitmentEventRepository(Protocol):
    async def get(self, event_id: UUID) -> RecruitmentEvent | None: ...

    async def add(self, event: RecruitmentEvent) -> None: ...

    async def list_active_for_application(
        self,
        application_id: UUID,
    ) -> Sequence[RecruitmentEvent]: ...


class ActionItemRepository(Protocol):
    async def get(self, action_item_id: UUID) -> ActionItem | None: ...

    async def add(self, action_item: ActionItem) -> None: ...

    async def list_open_for_application(self, application_id: UUID) -> Sequence[ActionItem]: ...


class UnitOfWork(Protocol):
    """Atomic boundary for domain mutations."""

    applications: ApplicationRepository
    events: RecruitmentEventRepository
    action_items: ActionItemRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
