"""Azure Storage Queue adapter containing operation identifiers only."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from azure.identity.aio import DefaultAzureCredential
from azure.storage.queue.aio import QueueClient

from recruitment_agent.config.settings import OperationsSettings


class AzureStorageOperationQueue:
    """Enqueue only opaque database operation IDs; no email data crosses the queue."""

    def __init__(self, client: QueueClient) -> None:
        self._client = client

    async def enqueue(self, *, operation_id: UUID) -> None:
        await self._client.send_message(
            json.dumps({"operation_id": str(operation_id)}, separators=(",", ":"))
        )


@asynccontextmanager
async def azure_operation_queue(
    settings: OperationsSettings,
) -> AsyncIterator[AzureStorageOperationQueue]:
    """Open a local connection-string client or a managed-identity cloud client."""
    connection_string = os.getenv("AzureWebJobsStorage")  # noqa: SIM112
    if connection_string:
        client = QueueClient.from_connection_string(
            connection_string,
            queue_name=settings.ops_queue_name,
        )
        async with client:
            yield AzureStorageOperationQueue(client)
        return

    account_name = os.getenv(
        "AzureWebJobsStorage__accountName",  # noqa: SIM112
        "",
    ).strip()
    if not account_name:
        raise RuntimeError("AzureWebJobsStorage__accountName is required for operations queue")
    managed_identity_client_id = (
        os.getenv("AzureWebJobsStorage__clientId")  # noqa: SIM112
        or os.getenv("AZURE_CLIENT_ID")
        or None
    )
    credential = DefaultAzureCredential(
        managed_identity_client_id=managed_identity_client_id
    )
    client = QueueClient(
        account_url=f"https://{account_name}.queue.core.windows.net",
        queue_name=settings.ops_queue_name,
        credential=credential,
    )
    try:
        async with client:
            yield AzureStorageOperationQueue(client)
    finally:
        await credential.close()
