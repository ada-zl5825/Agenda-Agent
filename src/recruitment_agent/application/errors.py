"""Application-layer failures with privacy-safe stable codes."""


class ApplicationError(RuntimeError):
    """Base class for expected application-service failures."""

    code = "APPLICATION_ERROR"


class AuthenticationRequiredError(ApplicationError):
    code = "AUTH_REQUIRED"


class AuthenticationFailedError(ApplicationError):
    code = "GRAPH_AUTH_ERROR"


class GraphFetchError(ApplicationError):
    code = "GRAPH_FETCH_FAILED"


class GraphRateLimitedError(GraphFetchError):
    code = "GRAPH_RATE_LIMITED"


class DeltaStateInvalidError(GraphFetchError):
    code = "DELTA_STATE_INVALID"


class MailSyncInProgressError(ApplicationError):
    """Another synchronization currently holds the folder's sync lease."""

    code = "SYNC_IN_PROGRESS"


class MailSyncPageLimitError(ApplicationError):
    """One invocation hit its page budget; committed progress resumes next run."""

    code = "SYNC_PAGE_LIMIT"


class TokenCacheConflictError(ApplicationError):
    code = "TOKEN_CACHE_CONFLICT"


class EmailNormalizationError(ApplicationError):
    code = "EMAIL_NORMALIZATION_FAILED"


class PrivacySanitizationError(ApplicationError):
    code = "PRIVACY_SANITIZATION_FAILED"


class LinkExtractionError(ApplicationError):
    code = "LINK_EXTRACTION_FAILED"


class LinkEncryptionError(ApplicationError):
    code = "LINK_ENCRYPTION_FAILED"


class ExtractionInputError(ApplicationError):
    code = "EXTRACTION_INPUT_REJECTED"


class ExtractionInvocationError(ApplicationError):
    code = "EXTRACTION_INVOCATION_FAILED"

    def __init__(
        self,
        message: str = "structured extraction failed",
        *,
        provider_failure: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_failure = provider_failure


class TimeEvidenceUnresolvedError(ApplicationError):
    """Time evidence exists but stayed unusable after review; fail visibly."""

    code = "EVENT_TIME_UNRESOLVED"

    def __init__(self, reason: str) -> None:
        super().__init__(f"time evidence is unresolved: {reason}")
        normalized = reason.strip().upper()
        if normalized:
            self.code = normalized[:64]


class CalendarCreateError(ApplicationError):
    code = "CALENDAR_CREATE_FAILED"


class CalendarUpdateError(ApplicationError):
    code = "CALENDAR_UPDATE_FAILED"


class CalendarEventNotFoundError(CalendarUpdateError):
    """The event linked in PostgreSQL no longer exists in the provider."""


class BriefSendError(ApplicationError):
    code = "BRIEF_SEND_FAILED"


class BriefSendUncertainError(BriefSendError):
    """Delivery may have been accepted; automatic retry could duplicate mail."""


class ReviewAuthenticationError(ApplicationError):
    code = "AUTH_REQUIRED"


class ReviewAccessDeniedError(ApplicationError):
    code = "REVIEW_ACCESS_DENIED"


class ReviewNotFoundError(ApplicationError):
    code = "REVIEW_NOT_FOUND"


class ReviewConflictError(ApplicationError):
    code = "REVIEW_CONFLICT"


class CsrfValidationError(ApplicationError):
    code = "CSRF_INVALID"


class OperationsAuthenticationError(ApplicationError):
    code = "OPS_AUTH_REQUIRED"


class OperationNotFoundError(ApplicationError):
    code = "OPERATION_NOT_FOUND"


class OperationConflictError(ApplicationError):
    code = "OPERATION_CONFLICT"


class OperationDisabledError(ApplicationError):
    code = "OPERATION_DISABLED"
