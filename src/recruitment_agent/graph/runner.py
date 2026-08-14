"""Application-facing start and resume operations for a compiled workflow."""

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, Interrupt

from recruitment_agent.application.errors import ApplicationError
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_VERSION
from recruitment_agent.graph.builder import RecruitmentCompiledGraph
from recruitment_agent.graph.context import RecruitmentGraphContext
from recruitment_agent.graph.contracts import (
    ProcessingRunStatus,
    ReviewDecision,
    WorkflowStage,
)
from recruitment_agent.graph.state import RecruitmentGraphInput, RecruitmentGraphState


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowStartRequest:
    source_email_id: UUID
    model_deployment: str | None
    processing_run_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class WorkflowInvocationResult:
    state: RecruitmentGraphState
    interrupt_payloads: tuple[dict[str, object], ...]

    @property
    def interrupted(self) -> bool:
        return bool(self.interrupt_payloads)

    def __repr__(self) -> str:
        return (
            "WorkflowInvocationResult("
            f"status={self.state['status']!r}, interrupted={self.interrupted})"
        )


class RecruitmentWorkflowRunner:
    def __init__(
        self,
        *,
        graph: RecruitmentCompiledGraph,
        context: RecruitmentGraphContext,
    ) -> None:
        self._graph = graph
        self._context = context

    _FINAL_RUN_STATUSES = frozenset(
        {
            ProcessingRunStatus.COMPLETED,
            ProcessingRunStatus.IGNORED,
            ProcessingRunStatus.FAILED,
        }
    )

    async def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        processing_run_id = request.processing_run_id or uuid4()
        thread_id = str(processing_run_id)
        # Retries reuse the same run id. Re-invoking a finished LangGraph thread
        # would re-execute nodes from START and drag a PROCESSED email back into
        # processing, so a finished run is returned as-is instead.
        existing = await self._context.persistence.get_run_status(processing_run_id)
        if existing in self._FINAL_RUN_STATUSES:
            final_state = cast(
                RecruitmentGraphState,
                {
                    "processing_run_id": str(processing_run_id),
                    "graph_thread_id": thread_id,
                    "source_email_id": str(request.source_email_id),
                    "status": existing.value,
                },
            )
            return WorkflowInvocationResult(state=final_state, interrupt_payloads=())
        initial: RecruitmentGraphInput = {
            "processing_run_id": str(processing_run_id),
            "graph_thread_id": thread_id,
            "source_email_id": str(request.source_email_id),
            "prompt_version": RECRUITMENT_EXTRACTION_PROMPT_VERSION,
            "model_deployment": request.model_deployment,
            "current_stage": WorkflowStage.LOAD_SOURCE_EMAIL.value,
            "status": ProcessingRunStatus.RUNNING.value,
        }
        return await self._invoke(
            initial,
            processing_run_id=processing_run_id,
            source_email_id=request.source_email_id,
            thread_id=thread_id,
        )

    async def resume(
        self,
        *,
        processing_run_id: UUID,
        source_email_id: UUID,
        decision: ReviewDecision,
    ) -> WorkflowInvocationResult:
        thread_id = str(processing_run_id)
        return await self._invoke(
            Command(resume=decision.model_dump(mode="json")),
            processing_run_id=processing_run_id,
            source_email_id=source_email_id,
            thread_id=thread_id,
        )

    async def _invoke(
        self,
        graph_input: RecruitmentGraphInput | Command[Any],
        *,
        processing_run_id: UUID,
        source_email_id: UUID,
        thread_id: str,
    ) -> WorkflowInvocationResult:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        try:
            raw = await self._graph.ainvoke(
                graph_input,
                config=config,
                context=self._context,
            )
        except Exception as exc:
            error_code = exc.code if isinstance(exc, ApplicationError) else "WORKFLOW_FAILED"
            await self._context.persistence.finalize_run(
                processing_run_id=processing_run_id,
                source_email_id=source_email_id,
                stage=WorkflowStage.FINALIZE_PROCESSING,
                status=ProcessingRunStatus.FAILED,
                finished_at=self._context.clock.now(),
                error_code=error_code,
                error_detail_sanitized=type(exc).__name__,
            )
            raise

        raw_state = cast(dict[str, object], raw)
        state = cast(RecruitmentGraphState, raw_state)
        raw_interrupts = cast(tuple[Interrupt, ...], raw_state.get("__interrupt__", ()))
        payloads = tuple(
            cast(dict[str, object], item.value)
            for item in raw_interrupts
            if isinstance(item.value, dict)
        )
        if payloads:
            # The email is waiting on a human decision, not actively running;
            # the distinct status keeps retries and dashboards from touching it.
            await self._context.persistence.mark_source_needs_review(source_email_id)
        return WorkflowInvocationResult(state=state, interrupt_payloads=payloads)
