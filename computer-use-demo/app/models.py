"""
Pydantic schemas and SQLAlchemy ORM models for session management.
"""

import enum
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


# ──────────────────────────────────────────────
# SQLAlchemy ORM Models
# ──────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class SessionStatus(str, enum.Enum):
    CREATED = "created"
    RUNNING = "running"
    IDLE = "idle"
    ERROR = "error"
    STOPPED = "stopped"


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, default="Untitled Session")
    status = Column(SAEnum(SessionStatus), default=SessionStatus.CREATED, nullable=False)
    model = Column(String, nullable=False, default="claude-sonnet-4-5-20250929")
    provider = Column(String, nullable=False, default="anthropic")
    system_prompt = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    messages = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan", order_by="MessageModel.created_at")


class MessageModel(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # "user", "assistant", "tool"
    content = Column(JSON, nullable=False)  # Stores the full message content (list or str)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("SessionModel", back_populates="messages")


# ──────────────────────────────────────────────
# Pydantic Request / Response Schemas
# ──────────────────────────────────────────────

class SessionCreate(BaseModel):
    name: str = Field(default="Untitled Session", max_length=200)
    model: str = Field(default="claude-sonnet-4-5-20250929")
    provider: str = Field(default="anthropic")
    system_prompt: str = Field(default="")


class SessionResponse(BaseModel):
    id: str
    name: str
    status: SessionStatus
    model: str
    provider: str
    system_prompt: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=50000)


class MessageResponse(BaseModel):
    id: int
    session_id: str
    role: str
    content: Any
    created_at: datetime

    class Config:
        from_attributes = True


class SessionDetailResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]


class ErrorResponse(BaseModel):
    detail: str


class SSEEvent(BaseModel):
    """Schema for SSE events pushed to the client."""
    event: str  # "text", "tool_use", "tool_result", "screenshot", "error", "done", "status"
    data: Any


class StopResponse(BaseModel):
    message: str
    session_id: str
