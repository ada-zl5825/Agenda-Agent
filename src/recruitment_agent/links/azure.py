"""Managed-identity composition for the Azure Key Vault link-key provider."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient

from recruitment_agent.config.settings import LinkEncryptionSettings
from recruitment_agent.links.key_provider import AzureKeyVaultLinkKeyProvider, LinkKeyProvider


@asynccontextmanager
async def azure_link_key_provider(
    settings: LinkEncryptionSettings,
) -> AsyncIterator[LinkKeyProvider]:
    """Own and close async Azure credentials/clients at the composition boundary."""
    credential = DefaultAzureCredential()
    async with (
        credential,
        SecretClient(
            vault_url=str(settings.azure_key_vault_url),
            credential=credential,
        ) as client,
    ):
        yield AzureKeyVaultLinkKeyProvider(
            client=client,
            secret_name=settings.link_encryption_key_secret_name,
            timeout_seconds=settings.key_vault_request_timeout_seconds,
        )
