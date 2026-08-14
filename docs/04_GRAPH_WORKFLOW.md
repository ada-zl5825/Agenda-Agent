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
                  -> request_review               (multiple/unresolved applications)
                  -> resolve_existing_event
                     -> request_review            (uncertain reschedule)
                  -> plan_state_transition
                  -> persist_domain_changes
                  -> sync_calendar_placeholder   (stable checkpoint node ID; real Phase 7 sync)
                       -> request_review          (unsafe create/update)
                       -> finalize_processing
```

Email fetching, action-link encryption, normalization and sanitization execute inside one transient
activity. The activity returns only sanitized text, opaque link refs and safe metadata before the
first of those values can be checkpointed. Separate graph nodes retain the required explicit
workflow stages and validate that safe boundary; they never checkpoint the transient Graph body.

The Phase 6 domain nodes now call a provider-neutral service. Resolution nodes are read-only and
checkpoint only typed IDs/candidates. `plan_state_transition` creates an intent; only
`persist_domain_changes` may write domain state, and it does so through one transaction that
revalidates source/application/event identities. The Phase 7 calendar node reloads authoritative
domain data, plans a safe provider-neutral event, and only then invokes the Graph adapter. Its old
`sync_calendar_placeholder` node ID is intentionally retained so Phase 5/6 durable checkpoints can
resume after deployment.

## Persistence and resume contract

- `app.processing_runs` is the durable audit of stage, status, prompt/model version and safe errors.
- `app.llm_extractions` stores only validated structured output and deterministic company/role
  evidence. A stable extraction ID makes replay return the first persisted result.
- `app.review_items` stores a stable typed question, allowed choices, resolution and optimistic
  version. It never contains the checkpoint payload.
- `agent_checkpoint.*` contains the LangGraph checkpointer tables isolated from `app.*`.
- `TIMEZONE_AMBIGUITY` pauses only for `TIMEZONE_AMBIGUOUS`. The model extracts the
  wall-clock even when the source omits a timezone; resume rebinds that clock to the
  chosen IANA zone. The `+00:00` schema placeholder is not UTC. If the clock is also
  unparsed, the same interrupt asks for timezone plus `YYYY-MM-DD HH:MM` (`timezone_and_datetime`
  or `timezone_and_deadline`) so the operator stays on one page.
- `DATETIME_CONFLICT` pauses for a remaining unparsed clock only when timezone was already
  resolved, with `use_override` (`YYYY-MM-DD HH:MM`) or `ignore`. The form labels the field
  as start time or deadline. After resolve, the browser continues to the next open review
  for the same source email, or back to the queue.
- `APPLICATION_AMBIGUITY` also pauses through `interrupt()`. Resume uses a typed
  `ReviewDecision`; invalid/stale decisions do not advance the workflow.
- A workflow `ApplicationError` after resume redirects back to the same review page with an
  opaque error code. It does not return raw 502 JSON.
- `UNCERTAIN_RESCHEDULE` pauses when zero or multiple active interviews could be the target. Resume
  may select one candidate, explicitly treat the evidence as a new interview, or ignore it.
- `UNSAFE_CALENDAR_UPDATE` pauses when a linked event disappeared or another Calendar invariant
  would be violated. Review may approve replacement, skip the Calendar update, or ignore the
  workflow. A missing linked provider event is never silently recreated.
- Side effects before an interrupt are idempotent because an interrupted node restarts when
  resumed.

The production composition functions `run_mail_processing_job` and
`resume_mail_processing_job` reconstruct all adapters and the graph around the same PostgreSQL
checkpointer. Phase 6 composition also supplies the atomic PostgreSQL domain store. Selecting
pending mail and exposing the graphical Review command are later phases.

## Daily Brief review navigation contract

Every future Daily Brief `NEEDS REVIEW` item must link to the authenticated graphical route
`/reviews/{review_id}` using only an opaque review ID. The email is a notification surface, not a
decision surface: a GET from an email client cannot resolve a review, resume a graph, write domain
state or update Calendar.

The authenticated Review and Brief preview pages reuse the Agent console visual chrome. The
detail page renders a deterministic read model assembled from PostgreSQL source-of-truth data:

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
