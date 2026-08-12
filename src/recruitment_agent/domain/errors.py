"""Domain-level errors independent from transport and persistence."""


class DomainValidationError(ValueError):
    """Raised when a domain object violates a deterministic invariant."""
