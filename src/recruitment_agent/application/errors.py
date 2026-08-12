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


class TokenCacheConflictError(ApplicationError):
    code = "TOKEN_CACHE_CONFLICT"


class EmailNormalizationError(ApplicationError):
    code = "EMAIL_NORMALIZATION_FAILED"


class PrivacySanitizationError(ApplicationError):
    code = "PRIVACY_SANITIZATION_FAILED"
