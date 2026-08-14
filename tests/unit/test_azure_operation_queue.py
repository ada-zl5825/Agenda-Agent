import base64

import pytest

import recruitment_agent.operations.azure_queue as queue_module
from recruitment_agent.config.settings import OperationsSettings
from recruitment_agent.operations.azure_queue import azure_operation_queue


def _settings() -> OperationsSettings:
    return OperationsSettings(
        ops_api_token=base64.b64encode(b"o" * 32).decode("ascii")
    )


@pytest.mark.asyncio
async def test_managed_identity_queue_transport_can_open_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AzureWebJobsStorage", raising=False)
    monkeypatch.setenv("AzureWebJobsStorage__accountName", "exampleaccount")
    monkeypatch.delenv("AzureWebJobsStorage__clientId", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)

    async with azure_operation_queue(_settings()):
        pass


@pytest.mark.asyncio
async def test_queue_uses_the_storage_managed_identity_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_client_id: str | None = None

    class Credential:
        def __init__(self, *, managed_identity_client_id: str | None) -> None:
            nonlocal selected_client_id
            selected_client_id = managed_identity_client_id

        async def close(self) -> None:
            pass

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> None:
            pass

    monkeypatch.delenv("AzureWebJobsStorage", raising=False)
    monkeypatch.setenv("AzureWebJobsStorage__accountName", "exampleaccount")
    monkeypatch.setenv("AzureWebJobsStorage__clientId", "storage-client-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "generic-client-id")
    monkeypatch.setattr(queue_module, "DefaultAzureCredential", Credential)
    monkeypatch.setattr(queue_module, "QueueClient", Client)

    async with azure_operation_queue(_settings()):
        pass

    assert selected_client_id == "storage-client-id"
