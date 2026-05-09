"""Tests for upload size limit middleware."""
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_upload_under_limit_passes(client):
    """100MB upload, limit 500MB → passes."""
    response = await client.post("/upload", headers={"content-length": "104857600"})
    assert response.status_code != 413


@pytest.mark.asyncio
async def test_upload_over_limit_returns_413(client):
    """600MB upload, limit 500MB → 413."""
    response = await client.post("/upload", headers={"content-length": "629145600"})
    assert response.status_code == 413
    data = response.json()
    assert "max_mb" in data
    assert "received_mb" in data


@pytest.mark.asyncio
async def test_upload_no_content_length_passes(client):
    """POST without Content-Length (chunked) → passes."""
    response = await client.post("/upload")
    assert response.status_code != 413


@pytest.mark.asyncio
async def test_get_request_not_checked(client):
    """GET with large Content-Length → passes (only POST/PUT/PATCH)."""
    response = await client.get("/api/health/worker", headers={"content-length": "629145600"})
    assert response.status_code != 413
