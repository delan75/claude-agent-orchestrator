"""
Tests for the async SQLite database layer.
"""

import asyncio
from unittest import mock

import pytest

# Patch database path before importing
with mock.patch.dict("os.environ", {"DATABASE_PATH": ":memory:"}):
    from app.database import (
        create_session,
        delete_session,
        get_message_count,
        get_messages,
        get_session,
        init_db,
        list_sessions,
        save_message,
        save_messages_bulk,
        update_session_status,
        engine,
    )
    from app.models import Base, SessionStatus


@pytest.fixture(autouse=True)
async def setup_db():
    """Create a fresh database for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ─── Session CRUD ───

async def test_create_and_get_session():
    """Test creating and retrieving a session."""
    session = await create_session(
        name="Test Session",
        model="claude-sonnet-4-5-20250929",
        provider="anthropic",
        system_prompt="Test prompt",
    )
    assert session.id is not None
    assert session.name == "Test Session"
    assert session.status == SessionStatus.CREATED

    # Retrieve it
    retrieved = await get_session(session.id)
    assert retrieved is not None
    assert retrieved.name == "Test Session"
    assert retrieved.model == "claude-sonnet-4-5-20250929"


async def test_list_sessions():
    """Test listing sessions."""
    await create_session(name="A")
    await create_session(name="B")

    sessions = await list_sessions()
    assert len(sessions) == 2
    # Newest first
    assert sessions[0].name == "B"
    assert sessions[1].name == "A"


async def test_update_session_status():
    """Test updating session status."""
    session = await create_session(name="Status Test")
    await update_session_status(session.id, SessionStatus.RUNNING)

    updated = await get_session(session.id)
    assert updated.status == SessionStatus.RUNNING


async def test_delete_session():
    """Test deleting a session."""
    session = await create_session(name="To Delete")
    result = await delete_session(session.id)
    assert result is True

    # Verify deletion
    assert await get_session(session.id) is None

    # Delete non-existent
    result = await delete_session("nonexistent")
    assert result is False


# ─── Message CRUD ───

async def test_save_and_get_messages():
    """Test saving and retrieving messages."""
    session = await create_session(name="Msg Test")

    await save_message(session.id, "user", [{"type": "text", "text": "Hello"}])
    await save_message(session.id, "assistant", [{"type": "text", "text": "Hi there!"}])

    messages = await get_messages(session.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


async def test_get_message_count():
    """Test message counting."""
    session = await create_session(name="Count Test")
    assert await get_message_count(session.id) == 0

    await save_message(session.id, "user", "Hello")
    await save_message(session.id, "assistant", "Hi")
    assert await get_message_count(session.id) == 2


async def test_save_messages_bulk():
    """Test bulk message saving (replaces existing messages)."""
    session = await create_session(name="Bulk Test")

    # Save initial messages
    await save_message(session.id, "user", "Old message")
    assert await get_message_count(session.id) == 1

    # Bulk save replaces all
    await save_messages_bulk(session.id, [
        {"role": "user", "content": "New message 1"},
        {"role": "assistant", "content": "New response 1"},
        {"role": "user", "content": "New message 2"},
    ])

    messages = await get_messages(session.id)
    assert len(messages) == 3
    assert messages[0].role == "user"
    assert messages[0].content == "New message 1"


async def test_cascade_delete_messages():
    """Test that deleting a session cascades to its messages."""
    session = await create_session(name="Cascade Test")
    await save_message(session.id, "user", "Hello")
    await save_message(session.id, "assistant", "Hi")

    await delete_session(session.id)
    messages = await get_messages(session.id)
    assert len(messages) == 0


# ─── Concurrent Access ───

async def test_concurrent_session_creation():
    """Test creating sessions concurrently without race conditions."""
    tasks = [create_session(name=f"Concurrent {i}") for i in range(10)]
    sessions = await asyncio.gather(*tasks)

    assert len(sessions) == 10
    ids = [s.id for s in sessions]
    assert len(set(ids)) == 10  # All unique
