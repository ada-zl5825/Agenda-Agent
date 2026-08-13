"""Phase 4 application service for sanitized semantic extraction."""

import re

from recruitment_agent.application.errors import ExtractionInputError
from recruitment_agent.application.secure_email_processing import SecurePreparedEmail
from recruitment_agent.extraction.models import (
    RecruitmentExtractionOutcome,
    RecruitmentExtractionRequest,
)
from recruitment_agent.extraction.ports import RecruitmentExtractionModel
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_VERSION
from recruitment_agent.extraction.validator import ExtractionValidator

_PLAINTEXT_URL = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]*://|\bmailto:|\bwww\.)")
_SECRET_QUERY_FRAGMENT = re.compile(
    r"(?i)(?:[?&]|\b)(?:access_token|auth|code|key|sig|signature|token)="
)
_ACTION_LINK_REF = re.compile(r"\bACTION_LINK_[0-9]{2,}\b")
_ACTION_LINK_TOKEN = re.compile(r"\bACTION_LINK_[A-Z0-9_]+\b")


class RecruitmentExtractionService:
    """Invoke semantic extraction without mutating domain or workflow state."""

    def __init__(
        self,
        *,
        model: RecruitmentExtractionModel,
        validator: ExtractionValidator | None = None,
    ) -> None:
        self._model = model
        self._validator = validator or ExtractionValidator()

    async def extract(self, prepared: SecurePreparedEmail) -> RecruitmentExtractionOutcome:
        request = build_extraction_request(prepared)
        extraction = await self._model.extract(request)
        validation = self._validator.validate(extraction, request)
        return RecruitmentExtractionOutcome(
            extraction=extraction,
            validation=validation,
            prompt_version=request.prompt_version,
        )


def build_extraction_request(prepared: SecurePreparedEmail) -> RecruitmentExtractionRequest:
    """Enforce the sanitized-only model boundary before any external call."""
    sanitized_text = prepared.sanitized.text
    if not sanitized_text.strip():
        raise ExtractionInputError("sanitized model evidence must not be empty")
    if _PLAINTEXT_URL.search(sanitized_text) or _SECRET_QUERY_FRAGMENT.search(sanitized_text):
        raise ExtractionInputError("sanitized model evidence contains a forbidden URL fragment")

    received_at = prepared.normalized.received_at
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ExtractionInputError("email received_at must be timezone-aware")

    source_email_id = prepared.normalized.source_email_id
    refs: list[str] = []
    for link in prepared.secure_links:
        if link.source_email_id != source_email_id:
            raise ExtractionInputError("secure link belongs to a different source email")
        if _ACTION_LINK_REF.fullmatch(link.ref) is None:
            raise ExtractionInputError("secure link reference is malformed")
        refs.append(link.ref)

    if len(refs) != len(set(refs)):
        raise ExtractionInputError("secure link references must be unique")

    allowed_link_refs = tuple(refs)
    evidence_refs = set(_ACTION_LINK_TOKEN.findall(sanitized_text))
    if any(_ACTION_LINK_REF.fullmatch(ref) is None for ref in evidence_refs):
        raise ExtractionInputError("sanitized evidence contains a malformed link reference")
    if not evidence_refs.issubset(allowed_link_refs):
        raise ExtractionInputError("sanitized evidence contains an unknown link reference")

    return RecruitmentExtractionRequest(
        source_email_id=source_email_id,
        received_at=received_at,
        sanitized_text=sanitized_text,
        allowed_link_refs=allowed_link_refs,
        prompt_version=RECRUITMENT_EXTRACTION_PROMPT_VERSION,
    )
