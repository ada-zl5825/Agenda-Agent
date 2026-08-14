"""Constant-time bearer-token authentication for the operations API."""

from hmac import compare_digest

from recruitment_agent.application.errors import OperationsAuthenticationError


class OperationsTokenAuthenticator:
    def __init__(self, expected_token: str) -> None:
        self._expected_token = expected_token

    def authenticate(self, supplied_token: str | None) -> None:
        if supplied_token is None or not compare_digest(
            supplied_token.encode("utf-8"),
            self._expected_token.encode("utf-8"),
        ):
            raise OperationsAuthenticationError("operations bearer token is invalid")
