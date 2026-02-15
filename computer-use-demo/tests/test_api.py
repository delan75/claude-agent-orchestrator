"""
Tests for the FastAPI session management API.
Uses httpx.AsyncClient with FastAPI test app.
"""

import json
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient

# Patch database path before importing app modules
with mock.patch.dict("os.environ", {"DATABASE_PATH": ":memory:"}):
    from app.database import init_db, engine, async_session_factory
    from app.main import app
    from app.models import Base


@pytest.fixture(autouse=True)
async def setup_db():
    """Create a fresh in-memory database for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """Async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ─── Session CRUD Tests ───

async def test_create_session(client):
    """Test creating a new session."""
    response = await client.post("/api/sessions", json={
        "name": "Test Session",
        "model": "claude-sonnet-4-5-20250929",
        "provider": "anthropic",
        "system_prompt": "Be helpful",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Session"
    assert data["model"] == "claude-sonnet-4-5-20250929"
    assert data["provider"] == "anthropic"
    assert data["status"] == "created"
    assert "id" in data


async def test_create_session_defaults(client):
    """Test creating a session with default values."""
    response = await client.post("/api/sessions", json={})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Untitled Session"
    assert data["model"] == "claude-sonnet-4-5-20250929"


async def test_list_sessions(client):
    """Test listing sessions."""
    # Create two sessions
    await client.post("/api/sessions", json={"name": "Session 1"})
    await client.post("/api/sessions", json={"name": "Session 2"})

    response = await client.get("/api/sessions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Most recent first
    assert data[0]["name"] == "Session 2"
    assert data[1]["name"] == "Session 1"


async def test_get_session(client):
    """Test getting session details."""
    create_resp = await client.post("/api/sessions", json={"name": "Detail Test"})
    session_id = create_resp.json()["id"]

    response = await client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["session"]["name"] == "Detail Test"
    assert data["messages"] == []


async def test_get_session_not_found(client):
    """Test getting a non-existent session."""
    response = await client.get("/api/sessions/nonexistent-id")
    assert response.status_code == 404


async def test_delete_session(client):
    """Test deleting a session."""
    create_resp = await client.post("/api/sessions", json={"name": "To Delete"})
    session_id = create_resp.json()["id"]

    response = await client.delete(f"/api/sessions/{session_id}")
    assert response.status_code == 204

    # Verify it's gone
    get_resp = await client.get(f"/api/sessions/{session_id}")
    assert get_resp.status_code == 404


async def test_delete_session_not_found(client):
    """Test deleting a non-existent session."""
    response = await client.delete("/api/sessions/nonexistent-id")
    assert response.status_code == 404


# ─── Message Endpoint Tests ───

async def test_send_message_requires_api_key(client):
    """Test that sending a message requires an API key."""
    create_resp = await client.post("/api/sessions", json={"name": "Msg Test"})
    session_id = create_resp.json()["id"]

    response = await client.post(
        f"/api/sessions/{session_id}/message",
        json={"content": "Hello"},
    )
    assert response.status_code == 400
    assert "API key" in response.json()["detail"]


async def test_send_message_session_not_found(client):
    """Test sending a message to a non-existent session."""
    response = await client.post(
        "/api/sessions/nonexistent/message",
        json={"content": "Hello"},
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 404


# ─── Stop Endpoint Tests ───

async def test_stop_session(client):
    """Test stopping a session."""
    create_resp = await client.post("/api/sessions", json={"name": "Stop Test"})
    session_id = create_resp.json()["id"]

    response = await client.post(f"/api/sessions/{session_id}/stop")
    assert response.status_code == 200
    assert "session_id" in response.json()


async def test_stop_session_not_found(client):
    """Test stopping a non-existent session."""
    response = await client.post("/api/sessions/nonexistent/stop")
    assert response.status_code == 404


# ─── Health Check ───

async def test_health_check(client):
    """Test health check endpoint."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


# ─── Concurrent Session Creation ───

async def test_concurrent_session_creation(client):
    """Test that multiple sessions can be created without race conditions."""
    import asyncio

    async def create_one(i):
        return await client.post("/api/sessions", json={"name": f"Concurrent {i}"})

    responses = await asyncio.gather(*[create_one(i) for i in range(5)])

    assert all(r.status_code == 201 for r in responses)
    ids = [r.json()["id"] for r in responses]
    assert len(set(ids)) == 5  # All unique IDs
