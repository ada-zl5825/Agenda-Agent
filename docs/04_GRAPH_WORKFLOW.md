# Workflow and Human Review Boundary

The Phase 5 mail-processing workflow will use an explicit LangGraph `StateGraph`. Graph state is
execution state; PostgreSQL domain tables remain the source of truth.

The current Phase 4 extraction layer preserves dependency boundaries so future workflow nodes can
invoke typed application services without coupling the domain to LangGraph.

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
