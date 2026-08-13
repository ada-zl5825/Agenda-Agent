"""Typed external boundary for semantic recruitment extraction."""

from typing import Protocol

from recruitment_agent.extraction.models import (
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)


class RecruitmentExtractionModel(Protocol):
    """An LLM may extract evidence but may not perform any side effect."""

    async def extract(self, request: RecruitmentExtractionRequest) -> RecruitmentExtraction: ...
