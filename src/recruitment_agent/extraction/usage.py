"""Task-local capture of extraction usage telemetry.

The extraction port intentionally returns evidence only, so the provider
adapter publishes token and latency telemetry out of band. Values live in a
``ContextVar``: concurrent workflow tasks each observe only their own call.
"""

from contextvars import ContextVar

from recruitment_agent.extraction.models import ExtractionUsage

_LAST_EXTRACTION_USAGE: ContextVar[ExtractionUsage | None] = ContextVar(
    "last_extraction_usage",
    default=None,
)


def record_extraction_usage(usage: ExtractionUsage | None) -> None:
    """Publish usage of the most recent extraction call in this task context."""
    _LAST_EXTRACTION_USAGE.set(usage)


def consume_extraction_usage() -> ExtractionUsage | None:
    """Read and clear the usage captured by the latest extraction call."""
    usage = _LAST_EXTRACTION_USAGE.get()
    _LAST_EXTRACTION_USAGE.set(None)
    return usage
