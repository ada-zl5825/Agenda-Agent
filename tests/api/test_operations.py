from base64 import b64encode

import httpx
import pytest

from recruitment_agent.api.app import create_app
from recruitment_agent.config import get_operations_settings


@pytest.mark.asyncio
async def test_operations_api_rejects_missing_or_wrong_bearer_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPS_API_TOKEN", b64encode(b"o" * 32).decode())
    get_operations_settings.cache_clear()
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get("/api/v1/ops/status")
            wrong = await client.get(
                "/api/v1/ops/status",
                headers={"Authorization": "Bearer wrong"},
            )
    finally:
        get_operations_settings.cache_clear()

    assert missing.status_code == 401
    assert missing.json() == {"error": "OPS_AUTH_REQUIRED"}
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert wrong.json() == {"error": "OPS_AUTH_REQUIRED"}


@pytest.mark.asyncio
async def test_liveness_does_not_require_operations_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPS_API_TOKEN", raising=False)
    get_operations_settings.cache_clear()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}
