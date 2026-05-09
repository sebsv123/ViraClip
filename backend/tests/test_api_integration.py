"""API integration tests using httpx.AsyncClient with FastAPI app."""
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_create_task_returns_200(client):
    """POST /tasks with valid URL returns 200/201 with task id."""
    response = await client.post("/api/tasks", json={
        "source_url": "https://youtube.com/watch?v=test123",
    })
    assert response.status_code in (200, 201)
    data = response.json()
    assert "id" in data or "task_id" in data


@pytest.mark.asyncio
async def test_create_task_invalid_url_returns_422(client):
    """POST /tasks with invalid URL returns 422."""
    response = await client.post("/api/tasks", json={
        "source_url": "not-a-url",
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_task_invalid_caption_template_returns_422(client):
    """POST /tasks with invalid caption_template returns 422."""
    response = await client.post("/api/tasks", json={
        "source_url": "https://youtube.com/watch?v=test123",
        "caption_template": "invalid_value",
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_task_not_found_returns_404(client):
    """GET /tasks/nonexistent returns 404."""
    response = await client.get("/api/tasks/99999999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_ready_returns_valid(client):
    """GET /health/ready returns 200 or 503 with status field."""
    response = await client.get("/api/health/ready")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_health_worker_returns_valid_schema(client):
    """GET /health/worker returns valid schema."""
    response = await client.get("/api/health/worker")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "workers_active" in data
    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "down")


@pytest.mark.asyncio
async def test_clip_stream_not_found_returns_404(client):
    """GET /clips/nonexistent/stream returns 404 (not 500)."""
    response = await client.get("/api/clips/99999999/stream")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_usage_returns_valid_schema(client):
    """GET /admin/usage returns valid schema."""
    response = await client.get("/api/admin/usage")
    assert response.status_code == 200
    data = response.json()
    assert "total_cost_today" in data
    assert isinstance(data["total_cost_today"], (int, float))
    assert "alert_level" in data
    assert data["alert_level"] in ("ok", "moderate", "high")


@pytest.mark.asyncio
async def test_longform_topic_too_short_returns_400(client):
    """POST /longform/create with short topic returns 400."""
    response = await client.post("/api/longform/create", json={
        "topic": "Hi",
        "duration_seconds": 600,
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_longform_duration_too_long_returns_400(client):
    """POST /longform/create with excessive duration returns 400."""
    response = await client.post("/api/longform/create", json={
        "topic": "A very interesting topic for a long video",
        "duration_seconds": 999999,
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_longform_duration_too_short_returns_400(client):
    """POST /longform/create with duration < 60s returns 400."""
    response = await client.post("/api/longform/create", json={
        "topic": "A very interesting topic for a long video",
        "duration_seconds": 30,
    })
    assert response.status_code == 400
