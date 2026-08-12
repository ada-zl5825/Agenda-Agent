# Workflow Boundary

The future mail-processing workflow uses an explicit LangGraph `StateGraph`. Graph state is execution state; PostgreSQL domain tables remain the source of truth.

Phase 0 does not install or implement the LangGraph runtime. It only preserves dependency boundaries so workflow nodes can later invoke typed application services without coupling the domain to LangGraph.
