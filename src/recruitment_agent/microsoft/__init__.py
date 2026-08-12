"""Microsoft identity and Graph infrastructure adapters."""

from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService
from recruitment_agent.microsoft.graph import GraphMailClient

__all__ = ["GraphMailClient", "MicrosoftAuthorizationService"]
