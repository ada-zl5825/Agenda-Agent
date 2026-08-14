"""Deterministic validation for user-configured delivery recipients."""

from __future__ import annotations


def normalize_recipient_address(value: str) -> str:
    """Return a bounded normalized mailbox address or raise ``ValueError``."""
    normalized = value.strip()
    if not normalized or len(normalized) > 254:
        raise ValueError("recipient address must contain between 1 and 254 characters")
    if any(character.isspace() or ord(character) < 32 for character in normalized):
        raise ValueError("recipient address must not contain whitespace or control characters")
    if normalized.count("@") != 1:
        raise ValueError("recipient address must contain exactly one @ character")
    local_part, domain = normalized.rsplit("@", maxsplit=1)
    if not local_part or not domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("recipient address is incomplete")
    if ".." in domain or any(not label for label in domain.split(".")):
        raise ValueError("recipient domain is invalid")
    return normalized
