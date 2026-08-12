---
name: structured-recruitment-extraction
description: Use when modifying recruitment LLM prompts, LangChain model integration, Azure OpenAI calls, Pydantic extraction schemas, structured outputs, model validation, confidence handling, or extraction fixtures.
---

# Structured Recruitment Extraction

Read `docs/01_FINAL_TECHNICAL_DESIGN.md` and the repository `AGENTS.md` before changing model extraction.

- Use typed Structured Outputs backed by Pydantic schemas; never parse prose output.
- Keep schemas in Python code and version prompts explicitly.
- Extract only facts supported by sanitized source content and return `None` when evidence is insufficient.
- Preserve exact source date and time strings.
- Never invent a timezone or infer one solely from company location.
- Accept and return only opaque `ACTION_LINK_*` references; never send original URLs to the model.
- Keep model deployment configurable and never hardcode a model name.
- Run every model result through deterministic validation before downstream use.
- Update contract fixtures and tests whenever prompts or schemas change.
