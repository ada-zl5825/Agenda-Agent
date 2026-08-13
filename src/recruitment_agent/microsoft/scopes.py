"""Least-privilege Microsoft Graph delegated scopes for Phase 1."""

MAIL_READ_SCOPES: tuple[str, ...] = ("User.Read", "Mail.Read")
GRAPH_DELEGATED_SCOPES: tuple[str, ...] = (
    *MAIL_READ_SCOPES,
    "Calendars.ReadWrite",
)

# MSAL adds openid, profile, and offline_access to the authorization request.
EXPECTED_OIDC_SCOPES: tuple[str, ...] = ("openid", "profile", "offline_access")

FORBIDDEN_PHASE_1_SCOPES: frozenset[str] = frozenset(
    {
        "Mail.ReadWrite",
        "Mail.Send",
    }
)
