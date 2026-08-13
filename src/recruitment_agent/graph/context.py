"""Per-invocation dependencies that are never written to graph checkpoints."""

from dataclasses import dataclass

from recruitment_agent.domain.ports import Clock
from recruitment_agent.graph.ports import (
    CalendarSyncPlaceholder,
    RecruitmentDomainActivities,
    RecruitmentWorkflowActivities,
    WorkflowPersistence,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RecruitmentGraphContext:
    activities: RecruitmentWorkflowActivities
    domain: RecruitmentDomainActivities
    persistence: WorkflowPersistence
    calendar: CalendarSyncPlaceholder
    clock: Clock
