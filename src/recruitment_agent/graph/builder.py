"""Explicit StateGraph construction for Phase 5 mail processing."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from recruitment_agent.graph.context import RecruitmentGraphContext
from recruitment_agent.graph.nodes import (
    extract_action_links,
    extract_recruitment_data,
    finalize_processing,
    load_source_email,
    mark_ignored,
    normalize_email,
    persist_domain_changes,
    plan_state_transition,
    prefilter_recruitment,
    request_review,
    resolve_application,
    resolve_existing_event,
    route_after_prefilter,
    route_after_validation,
    sanitize_content,
    sync_calendar_placeholder,
    validate_extraction,
)
from recruitment_agent.graph.state import RecruitmentGraphInput, RecruitmentGraphState

RecruitmentCompiledGraph = CompiledStateGraph[
    RecruitmentGraphState,
    RecruitmentGraphContext,
    RecruitmentGraphInput,
    RecruitmentGraphState,
]


def build_recruitment_graph(
    *,
    checkpointer: BaseCheckpointSaver[str],
) -> RecruitmentCompiledGraph:
    """Compile the deterministic workflow with durable interrupt support."""
    builder = StateGraph(
        RecruitmentGraphState,
        context_schema=RecruitmentGraphContext,
        input_schema=RecruitmentGraphInput,
        output_schema=RecruitmentGraphState,
    )
    builder.add_node("load_source_email", load_source_email)
    builder.add_node("normalize_email", normalize_email)
    builder.add_node("extract_action_links", extract_action_links)
    builder.add_node("prefilter_recruitment", prefilter_recruitment)
    builder.add_node("sanitize_content", sanitize_content)
    builder.add_node("extract_recruitment_data", extract_recruitment_data)
    builder.add_node("validate_extraction", validate_extraction)
    builder.add_node("request_review", request_review)
    builder.add_node("resolve_application", resolve_application)
    builder.add_node("resolve_existing_event", resolve_existing_event)
    builder.add_node("plan_state_transition", plan_state_transition)
    builder.add_node("persist_domain_changes", persist_domain_changes)
    builder.add_node("sync_calendar_placeholder", sync_calendar_placeholder)
    builder.add_node("finalize_processing", finalize_processing)
    builder.add_node("mark_ignored", mark_ignored)

    builder.add_edge(START, "load_source_email")
    builder.add_edge("load_source_email", "normalize_email")
    builder.add_edge("normalize_email", "extract_action_links")
    builder.add_edge("extract_action_links", "prefilter_recruitment")
    builder.add_conditional_edges(
        "prefilter_recruitment",
        route_after_prefilter,
        {
            "sanitize_content": "sanitize_content",
            "mark_ignored": "mark_ignored",
        },
    )
    builder.add_edge("sanitize_content", "extract_recruitment_data")
    builder.add_edge("extract_recruitment_data", "validate_extraction")
    builder.add_conditional_edges(
        "validate_extraction",
        route_after_validation,
        {
            "request_review": "request_review",
            "resolve_application": "resolve_application",
            "mark_ignored": "mark_ignored",
            "finalize_processing": "finalize_processing",
        },
    )
    builder.add_edge("resolve_application", "resolve_existing_event")
    builder.add_edge("resolve_existing_event", "plan_state_transition")
    builder.add_edge("plan_state_transition", "persist_domain_changes")
    builder.add_edge("persist_domain_changes", "sync_calendar_placeholder")
    builder.add_edge("sync_calendar_placeholder", "finalize_processing")
    builder.add_edge("finalize_processing", END)
    builder.add_edge("mark_ignored", END)
    return builder.compile(checkpointer=checkpointer)
