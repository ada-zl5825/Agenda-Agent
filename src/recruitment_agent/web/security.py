"""Short-lived signed browser sessions and review-bound CSRF protection."""

import base64
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from recruitment_agent.application.errors import (
    CsrfValidationError,
    ReviewAuthenticationError,
)
from recruitment_agent.domain.ports import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSession:
    connection_id: UUID
    admin_home_account_id: str
    admin_tenant_id: str | None
    expires_at: datetime
    nonce: str


class WebSessionManager:
    cookie_name = "recruitment_session"
    return_cookie_name = "recruitment_return"

    def __init__(self, *, key: bytes, clock: Clock, ttl_seconds: int = 28_800) -> None:
        if len(key) != 32:
            raise ValueError("web session signing key must be 32 bytes")
        self._key = key
        self._clock = clock
        self._ttl = timedelta(seconds=ttl_seconds)

    def issue(
        self,
        connection_id: UUID,
        *,
        admin_home_account_id: str,
        admin_tenant_id: str | None,
    ) -> str:
        normalized_admin = admin_home_account_id.strip()
        if not normalized_admin or len(normalized_admin) > 255:
            raise ValueError("admin home account ID is invalid")
        expires_at = self._clock.now() + self._ttl
        payload: dict[str, object] = {
            "connection_id": str(connection_id),
            "admin_home_account_id": normalized_admin,
            "admin_tenant_id": admin_tenant_id,
            "expires_at": int(expires_at.timestamp()),
            "nonce": secrets.token_urlsafe(18),
        }
        return self._sign_json(payload, purpose="session")

    @property
    def cookie_max_age(self) -> int:
        return int(self._ttl.total_seconds())

    def authenticate(self, token: str | None) -> WebSession:
        if token is None:
            raise ReviewAuthenticationError("browser authentication is required")
        payload = self._verify_json(token, purpose="session")
        try:
            expires_at_value = payload["expires_at"]
            if not isinstance(expires_at_value, (int, str)):
                raise TypeError("session expiry must be an integer")
            session = WebSession(
                connection_id=UUID(str(payload["connection_id"])),
                admin_home_account_id=str(payload["admin_home_account_id"]),
                admin_tenant_id=(
                    None
                    if payload.get("admin_tenant_id") is None
                    else str(payload["admin_tenant_id"])
                ),
                expires_at=datetime.fromtimestamp(
                    int(expires_at_value),
                    tz=UTC,
                ),
                nonce=str(payload["nonce"]),
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ReviewAuthenticationError("browser session is invalid") from exc
        if not session.admin_home_account_id or len(session.admin_home_account_id) > 255:
            raise ReviewAuthenticationError("browser session administrator is invalid")
        if session.expires_at <= self._clock.now():
            raise ReviewAuthenticationError("browser session has expired")
        return session

    def csrf_token(self, *, session_token: str, review_id: UUID, version: int) -> str:
        message = f"csrf:{session_token}:{review_id}:{version}".encode()
        return self._encode(hmac.digest(self._key, message, "sha256"))

    def verify_csrf(
        self,
        *,
        session_token: str,
        review_id: UUID,
        version: int,
        supplied: str,
    ) -> None:
        expected = self.csrf_token(
            session_token=session_token,
            review_id=review_id,
            version=version,
        )
        if not hmac.compare_digest(expected, supplied):
            raise CsrfValidationError("review CSRF token is invalid")

    def action_csrf_token(
        self,
        *,
        session_token: str,
        action: str,
        version: int,
    ) -> str:
        """Bind a browser mutation to its session, typed action, and control version."""
        if not action or not action.isascii() or len(action) > 80 or version < 1:
            raise ValueError("invalid CSRF action binding")
        message = f"csrf-action:{session_token}:{action}:{version}".encode()
        return self._encode(hmac.digest(self._key, message, "sha256"))

    def verify_action_csrf(
        self,
        *,
        session_token: str,
        action: str,
        version: int,
        supplied: str,
    ) -> None:
        expected = self.action_csrf_token(
            session_token=session_token,
            action=action,
            version=version,
        )
        if not hmac.compare_digest(expected, supplied):
            raise CsrfValidationError("agent console CSRF token is invalid")

    def issue_return_path(self, path: str) -> str:
        normalized = self.validate_return_path(path)
        expires_at = self._clock.now() + timedelta(minutes=10)
        return self._sign_json(
            {
                "path": normalized,
                "expires_at": int(expires_at.timestamp()),
            },
            purpose="return",
        )

    def read_return_path(self, token: str | None) -> str:
        if token is None:
            return "/agent"
        try:
            payload = self._verify_json(token, purpose="return")
            expires_at_value = payload["expires_at"]
            if not isinstance(expires_at_value, (int, str)):
                return "/agent"
            expires_at = datetime.fromtimestamp(int(expires_at_value), tz=UTC)
            if expires_at <= self._clock.now():
                return "/agent"
            return self.validate_return_path(str(payload["path"]))
        except (KeyError, TypeError, ValueError, OverflowError, ReviewAuthenticationError):
            return "/agent"

    @staticmethod
    def validate_return_path(path: str) -> str:
        if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
            return "/agent"
        return path if path.startswith(("/agent", "/reviews", "/brief/")) else "/agent"

    def _sign_json(self, payload: dict[str, object], *, purpose: str) -> str:
        encoded = self._encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        signature = self._encode(
            hmac.digest(self._key, f"{purpose}:{encoded}".encode(), "sha256")
        )
        return f"{encoded}.{signature}"

    def _verify_json(self, token: str, *, purpose: str) -> dict[str, object]:
        try:
            encoded, supplied = token.split(".", maxsplit=1)
            expected = self._encode(
                hmac.digest(self._key, f"{purpose}:{encoded}".encode(), "sha256")
            )
            if not hmac.compare_digest(expected, supplied):
                raise ValueError
            decoded = json.loads(self._decode(encoded))
            if not isinstance(decoded, dict):
                raise ValueError
            return decoded
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ReviewAuthenticationError("signed browser value is invalid") from exc

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)
