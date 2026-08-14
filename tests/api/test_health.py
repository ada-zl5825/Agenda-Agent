import httpx
import pytest

from recruitment_agent.api.app import create_app


@pytest.mark.asyncio
async def test_health_endpoint_has_no_external_dependency() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


@pytest.mark.asyncio
async def test_openapi_catalog_is_not_publicly_enumerable() -> None:
    """Regression: the control-plane path catalog must not be anonymous."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 404
