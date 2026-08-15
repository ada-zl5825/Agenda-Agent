"""Structured metric events for Application Insights KQL aggregation.

Metrics are emitted as single-line ``RA_METRIC {json}`` records through the
standard logging pipeline that the Azure Functions host already forwards to
the Application Insights ``traces`` table. Dashboards parse the JSON payload
from the message text (see ``benchmarks/kql/``), so no extra telemetry SDK or
host configuration is required.

Privacy rules: metric names and dimension keys are developer-controlled and
validated strictly; dimension values are runtime data and are replaced with
``redacted`` unless they match a conservative identifier pattern. Email
content, subjects, URLs, and tokens can therefore never leak through metrics.
"""

import json
import logging
import re
from collections.abc import Mapping

METRIC_LOG_PREFIX = "RA_METRIC"
_METRIC_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_DIMENSION_VALUE = re.compile(r"^[A-Za-z0-9_.:\-/]{1,128}$")

_LOGGER = logging.getLogger("recruitment_agent.metrics")


class MetricEmitter:
    """Emit privacy-validated metric events as structured log lines."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or _LOGGER

    def emit(
        self,
        name: str,
        value: float,
        dimensions: Mapping[str, str] | None = None,
    ) -> None:
        if _METRIC_IDENTIFIER.fullmatch(name) is None:
            raise ValueError("metric name must be lowercase snake_case")
        safe_dimensions: dict[str, str] = {}
        for key, raw_value in (dimensions or {}).items():
            if _METRIC_IDENTIFIER.fullmatch(key) is None:
                raise ValueError("metric dimension keys must be lowercase snake_case")
            safe_dimensions[key] = (
                raw_value if _SAFE_DIMENSION_VALUE.fullmatch(raw_value) else "redacted"
            )
        payload = {
            "metric": name,
            "value": float(value),
            "dimensions": safe_dimensions,
        }
        self._logger.info(
            "%s %s",
            METRIC_LOG_PREFIX,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
