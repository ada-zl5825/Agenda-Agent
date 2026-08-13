"""Deterministic validation for model-produced recruitment evidence."""

import re
from datetime import datetime

from recruitment_agent.domain.enums import RecruitmentEventType
from recruitment_agent.extraction.models import (
    ExtractionIssueCode,
    ExtractionIssueSeverity,
    ExtractionValidationIssue,
    ExtractionValidationResult,
    ExtractionValidationStatus,
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)

_ACTION_LINK_REF = re.compile(r"^ACTION_LINK_[0-9]{2,}$")


class ExtractionValidator:
    """Reject inconsistent output and mark genuine ambiguity for later review."""

    def __init__(self, *, confidence_threshold: float = 0.6) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self._confidence_threshold = confidence_threshold

    def validate(
        self,
        extraction: RecruitmentExtraction,
        request: RecruitmentExtractionRequest,
    ) -> ExtractionValidationResult:
        issues: list[ExtractionValidationIssue] = []
        self._validate_evidence_text(extraction, issues)
        self._validate_source_grounding(extraction, request, issues)
        self._validate_confidence(extraction, issues)
        self._validate_relevance(extraction, issues)
        self._validate_action(extraction, issues)
        self._validate_link_ref(extraction, request, issues)
        self._validate_time(extraction, issues)
        self._validate_event(extraction, issues)

        if any(issue.severity is ExtractionIssueSeverity.ERROR for issue in issues):
            status = ExtractionValidationStatus.INVALID
        elif issues:
            status = ExtractionValidationStatus.NEEDS_REVIEW
        else:
            status = ExtractionValidationStatus.VALID
        return ExtractionValidationResult(status=status, issues=tuple(issues))

    @staticmethod
    def _add(
        issues: list[ExtractionValidationIssue],
        *,
        code: ExtractionIssueCode,
        severity: ExtractionIssueSeverity,
        field: str,
    ) -> None:
        issues.append(ExtractionValidationIssue(code=code, severity=severity, field=field))

    def _validate_evidence_text(
        self,
        extraction: RecruitmentExtraction,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        fields = {
            "company_raw": extraction.company_raw,
            "role_raw": extraction.role_raw,
            "interview_round": extraction.interview_round,
            "action_text": extraction.action_text,
            "timezone_text": extraction.timezone_text,
            "source_datetime_text": extraction.source_datetime_text,
            "source_deadline_text": extraction.source_deadline_text,
            "meeting_platform": extraction.meeting_platform,
            "location": extraction.location,
        }
        for field, value in fields.items():
            if value is not None and not value.strip():
                self._add(
                    issues,
                    code=ExtractionIssueCode.BLANK_EVIDENCE,
                    severity=ExtractionIssueSeverity.ERROR,
                    field=field,
                )

    def _validate_confidence(
        self,
        extraction: RecruitmentExtraction,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        values = {
            "company_confidence": extraction.company_confidence,
            "event_confidence": extraction.event_confidence,
            "datetime_confidence": extraction.datetime_confidence,
        }
        for field, value in values.items():
            if not 0.0 <= value <= 1.0:
                self._add(
                    issues,
                    code=ExtractionIssueCode.CONFIDENCE_OUT_OF_RANGE,
                    severity=ExtractionIssueSeverity.ERROR,
                    field=field,
                )

        confidence_required = {
            "company_confidence": extraction.company_raw is not None,
            "event_confidence": extraction.relevant,
            "datetime_confidence": any(
                value is not None
                for value in (
                    extraction.event_datetime,
                    extraction.deadline,
                    extraction.source_datetime_text,
                    extraction.source_deadline_text,
                )
            ),
        }
        for field, required in confidence_required.items():
            if required and 0.0 <= values[field] < self._confidence_threshold:
                self._add(
                    issues,
                    code=ExtractionIssueCode.LOW_CONFIDENCE,
                    severity=ExtractionIssueSeverity.REVIEW,
                    field=field,
                )

    def _validate_source_grounding(
        self,
        extraction: RecruitmentExtraction,
        request: RecruitmentExtractionRequest,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        evidence_fields = {
            "company_raw": extraction.company_raw,
            "role_raw": extraction.role_raw,
            "interview_round": extraction.interview_round,
            "timezone_text": extraction.timezone_text,
            "source_datetime_text": extraction.source_datetime_text,
            "source_deadline_text": extraction.source_deadline_text,
            "meeting_platform": extraction.meeting_platform,
            "location": extraction.location,
        }
        for field, value in evidence_fields.items():
            if value is not None and value not in request.sanitized_text:
                self._add(
                    issues,
                    code=ExtractionIssueCode.EVIDENCE_NOT_FOUND,
                    severity=ExtractionIssueSeverity.ERROR,
                    field=field,
                )

    def _validate_relevance(
        self,
        extraction: RecruitmentExtraction,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        if extraction.relevant:
            if extraction.event_type is RecruitmentEventType.UNKNOWN:
                self._add(
                    issues,
                    code=ExtractionIssueCode.UNKNOWN_EVENT,
                    severity=ExtractionIssueSeverity.REVIEW,
                    field="event_type",
                )
            return

        semantic_values = (
            extraction.company_raw,
            extraction.role_raw,
            extraction.interview_round,
            extraction.action_text,
            extraction.action_link_ref,
            extraction.event_datetime,
            extraction.deadline,
            extraction.source_datetime_text,
            extraction.source_deadline_text,
            extraction.meeting_platform,
            extraction.location,
        )
        if (
            extraction.event_type is not RecruitmentEventType.UNKNOWN
            or extraction.action_required
            or any(value is not None for value in semantic_values)
        ):
            self._add(
                issues,
                code=ExtractionIssueCode.IRRELEVANT_FACT_CONFLICT,
                severity=ExtractionIssueSeverity.ERROR,
                field="relevant",
            )

    def _validate_action(
        self,
        extraction: RecruitmentExtraction,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        if extraction.action_required and extraction.action_text is None:
            self._add(
                issues,
                code=ExtractionIssueCode.ACTION_TEXT_MISSING,
                severity=ExtractionIssueSeverity.REVIEW,
                field="action_text",
            )
        elif not extraction.action_required and extraction.action_text is not None:
            self._add(
                issues,
                code=ExtractionIssueCode.ACTION_TEXT_CONFLICT,
                severity=ExtractionIssueSeverity.ERROR,
                field="action_text",
            )

    def _validate_link_ref(
        self,
        extraction: RecruitmentExtraction,
        request: RecruitmentExtractionRequest,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        ref = extraction.action_link_ref
        if ref is None:
            return
        if _ACTION_LINK_REF.fullmatch(ref) is None:
            self._add(
                issues,
                code=ExtractionIssueCode.MALFORMED_LINK_REF,
                severity=ExtractionIssueSeverity.ERROR,
                field="action_link_ref",
            )
        elif ref not in request.allowed_link_refs:
            self._add(
                issues,
                code=ExtractionIssueCode.UNKNOWN_LINK_REF,
                severity=ExtractionIssueSeverity.ERROR,
                field="action_link_ref",
            )

    def _validate_time(
        self,
        extraction: RecruitmentExtraction,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        self._validate_datetime_pair(
            normalized=extraction.event_datetime,
            source=extraction.source_datetime_text,
            normalized_field="event_datetime",
            source_field="source_datetime_text",
            missing_code=ExtractionIssueCode.DATETIME_SOURCE_MISSING,
            unresolved_code=ExtractionIssueCode.DATETIME_UNRESOLVED,
            issues=issues,
        )
        self._validate_datetime_pair(
            normalized=extraction.deadline,
            source=extraction.source_deadline_text,
            normalized_field="deadline",
            source_field="source_deadline_text",
            missing_code=ExtractionIssueCode.DEADLINE_SOURCE_MISSING,
            unresolved_code=ExtractionIssueCode.DEADLINE_UNRESOLVED,
            issues=issues,
        )

        has_time_evidence = any(
            value is not None
            for value in (
                extraction.event_datetime,
                extraction.deadline,
                extraction.source_datetime_text,
                extraction.source_deadline_text,
            )
        )
        if extraction.timezone_explicit:
            if extraction.timezone_text is None:
                self._add(
                    issues,
                    code=ExtractionIssueCode.TIMEZONE_CONFLICT,
                    severity=ExtractionIssueSeverity.ERROR,
                    field="timezone_text",
                )
            for field, value in (
                ("event_datetime", extraction.event_datetime),
                ("deadline", extraction.deadline),
            ):
                if value is not None and not self._is_aware(value):
                    self._add(
                        issues,
                        code=ExtractionIssueCode.DATETIME_NOT_AWARE,
                        severity=ExtractionIssueSeverity.ERROR,
                        field=field,
                    )
        elif extraction.timezone_text is not None:
            self._add(
                issues,
                code=ExtractionIssueCode.TIMEZONE_CONFLICT,
                severity=ExtractionIssueSeverity.ERROR,
                field="timezone_text",
            )
        elif has_time_evidence:
            self._add(
                issues,
                code=ExtractionIssueCode.TIMEZONE_AMBIGUOUS,
                severity=ExtractionIssueSeverity.REVIEW,
                field="timezone_explicit",
            )

    def _validate_datetime_pair(
        self,
        *,
        normalized: datetime | None,
        source: str | None,
        normalized_field: str,
        source_field: str,
        missing_code: ExtractionIssueCode,
        unresolved_code: ExtractionIssueCode,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        if normalized is not None and source is None:
            self._add(
                issues,
                code=missing_code,
                severity=ExtractionIssueSeverity.ERROR,
                field=source_field,
            )
        elif normalized is None and source is not None:
            self._add(
                issues,
                code=unresolved_code,
                severity=ExtractionIssueSeverity.REVIEW,
                field=normalized_field,
            )

    def _validate_event(
        self,
        extraction: RecruitmentExtraction,
        issues: list[ExtractionValidationIssue],
    ) -> None:
        if (
            extraction.event_type is RecruitmentEventType.INTERVIEW_RESCHEDULE
            and extraction.event_datetime is None
        ):
            self._add(
                issues,
                code=ExtractionIssueCode.RESCHEDULE_DATETIME_MISSING,
                severity=ExtractionIssueSeverity.REVIEW,
                field="event_datetime",
            )

    @staticmethod
    def _is_aware(value: datetime) -> bool:
        return value.tzinfo is not None and value.utcoffset() is not None
