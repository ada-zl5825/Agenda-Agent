# Workflow and Human Review Boundary

The Phase 5 mail-processing workflow uses an explicit LangGraph `StateGraph`. Graph state is
execution state; PostgreSQL domain tables remain the source of truth. A stable processing-run UUID
is also the checkpointer `thread_id`, so a new process can rebuild the graph and resume the same
interrupt.

## Implemented nodes and routing

```text
load_source_email
  -> normalize_email
  -> extract_action_links
  -> prefilter_recruitment
       -> mark_ignored                           (unlikely)
       -> sanitize_content                       (likely/unknown)
          -> extract_recruitment_data
          -> validate_extraction
               -> mark_ignored                   (not recruitment)
               -> finalize_processing            (invalid)
               -> request_review                 (ambiguous)
               -> resolve_application            (valid)
                  -> resolve_existing_event
                  -> plan_state_transition
                  -> persist_domain_changes
                  -> sync_calendar_placeholder
                  -> finalize_processing
```

Email fetching, action-link encryption, normalization and sanitization execute inside one transient
activity. The activity returns only sanitized text, opaque link refs and safe metadata before the
first of those values can be checkpointed. Separate graph nodes retain the required explicit
workflow stages and validate that safe boundary; they never checkpoint the transient Graph body.

Phase 6 domain nodes and the Phase 7 calendar node are typed no-ops in Phase 5. They make no domain
or external side effect.

## Persistence and resume contract

- `app.processing_runs` is the durable audit of stage, status, prompt/model version and safe errors.
- `app.llm_extractions` stores only validated structured output and deterministic company/role
  evidence. A stable extraction ID makes replay return the first persisted result.
- `app.review_items` stores a stable typed question, allowed choices, resolution and optimistic
  version. It never contains the checkpoint payload.
- `agent_checkpoint.*` contains the LangGraph checkpointer tables isolated from `app.*`.
- `TIMEZONE_AMBIGUITY`, `APPLICATION_AMBIGUITY` and `DATETIME_CONFLICT` pause through
  `interrupt()`. Resume uses a typed `ReviewDecision`; invalid/stale decisions do not advance the
  workflow.
- Side effects before an interrupt are idempotent because an interrupted node restarts when
  resumed.

The production composition functions `run_mail_processing_job` and
`resume_mail_processing_job` reconstruct all adapters and the graph around the same PostgreSQL
checkpointer. Selecting pending mail and exposing the graphical Review command are later phases.

## Daily Brief review navigation contract

Every future Daily Brief `NEEDS REVIEW` item must link to the authenticated graphical route
`/reviews/{review_id}` using only an opaque review ID. The email is a notification surface, not a
decision surface: a GET from an email client cannot resolve a review, resume a graph, write domain
state or update Calendar.

The detail page renders a deterministic read model assembled from PostgreSQL source-of-truth data:

- review ID/type/status/reason and age;
- safe source-email metadata and the Outlook original-email link;
- resolved and raw company/role evidence plus current application status;
- extracted event/action fields, exact time evidence, normalized values and confidences;
- current-versus-proposed values and ambiguity candidates;
- opaque secure-link ref/type/domain only;
- blocked/planned side effects;
- typed question, allowed choices and server-validated override controls; and
- resolution audit after completion.

The page never renders raw HTML/body, attachments, unnecessary PII, model prompts/completions,
OAuth credentials, graph checkpoint payloads or plaintext secure-link destinations. Review detail
loads do not decrypt action links. Resolution is an idempotent, CSRF-protected POST guarded by the
review's open status and optimistic version; only then may the workflow resume.
