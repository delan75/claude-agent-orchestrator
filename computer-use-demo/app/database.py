"""
Async SQLite database layer using SQLAlchemy async engine.
"""

import os
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base, MessageModel, SessionModel, SessionStatus

# Database file path — mountable via Docker volume
DB_PATH = os.environ.get("DATABASE_PATH", "/data/sessions.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """Yield an async database session."""
    async with async_session_factory() as session:
        yield session


# ──────────────────────────────────────────────
# Session CRUD
# ──────────────────────────────────────────────

async def create_session(
    name: str = "Untitled Session",
    model: str = "claude-sonnet-4-5-20250929",
    provider: str = "anthropic",
    system_prompt: str = "",
) -> SessionModel:
    """Create a new agent session."""
    session_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session = SessionModel(
        id=session_id,
        name=name,
        model=model,
        provider=provider,
        system_prompt=system_prompt,
        status=SessionStatus.CREATED,
        created_at=now,
        updated_at=now,
    )
    async with async_session_factory() as db:
        db.add(db_session)
        await db.commit()
        await db.refresh(db_session)
        return db_session


async def get_session(session_id: str) -> Optional[SessionModel]:
    """Get a session by ID."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == session_id)
        )
        return result.scalar_one_or_none()


async def list_sessions() -> list[SessionModel]:
    """List all sessions, newest first."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(SessionModel).order_by(SessionModel.created_at.desc())
        )
        return list(result.scalars().all())


async def update_session_status(session_id: str, status: SessionStatus) -> None:
    """Update session status."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session:
            session.status = status
            session.updated_at = datetime.utcnow()
            await db.commit()


async def delete_session(session_id: str) -> bool:
    """Delete a session and all its messages. Returns True if found and deleted."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            return False
        await db.delete(session)
        await db.commit()
        return True


async def get_message_count(session_id: str) -> int:
    """Get message count for a session."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(func.count(MessageModel.id)).where(MessageModel.session_id == session_id)
        )
        return result.scalar() or 0


# ──────────────────────────────────────────────
# Message CRUD
# ──────────────────────────────────────────────

async def save_message(session_id: str, role: str, content: Any) -> MessageModel:
    """Save a message to the database."""
    msg = MessageModel(
        session_id=session_id,
        role=role,
        content=content,
        created_at=datetime.utcnow(),
    )
    async with async_session_factory() as db:
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg


async def get_messages(session_id: str) -> list[MessageModel]:
    """Get all messages for a session, ordered by creation time."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(MessageModel)
            .where(MessageModel.session_id == session_id)
            .order_by(MessageModel.created_at)
        )
        return list(result.scalars().all())


async def save_messages_bulk(session_id: str, messages: list[dict]) -> None:
    """Save multiple messages at once (used to persist the full conversation after a loop)."""
    async with async_session_factory() as db:
        # Delete existing messages for this session first
        existing = await db.execute(
            select(MessageModel).where(MessageModel.session_id == session_id)
        )
        for msg in existing.scalars().all():
            await db.delete(msg)

        # Insert all messages
        now = datetime.utcnow()
        for msg_data in messages:
            msg = MessageModel(
                session_id=session_id,
                role=msg_data.get("role", "unknown"),
                content=msg_data.get("content", ""),
                created_at=now,
            )
            db.add(msg)
        await db.commit()
