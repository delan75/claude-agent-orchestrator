"""
REST API endpoints for session management.
"""

import json
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from .. import database as db
from ..models import (
    MessageCreate,
    MessageResponse,
    SessionCreate,
    SessionDetailResponse,
    SessionResponse,
    SessionStatus,
    StopResponse,
)
from ..session_manager import session_manager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(body: SessionCreate):
    """Create a new agent session."""
    session_id = await session_manager.create_session(
        name=body.name,
        model=body.model,
        provider=body.provider,
        system_prompt=body.system_prompt,
    )
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=500, detail="Failed to create session")
    msg_count = await db.get_message_count(session_id)
    return SessionResponse(
        id=session.id,
        name=session.name,
        status=session.status,
        model=session.model,
        provider=session.provider,
        system_prompt=session.system_prompt,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=msg_count,
    )


@router.get("", response_model=list[SessionResponse])
async def list_sessions():
    """List all sessions."""
    sessions = await db.list_sessions()
    result = []
    for s in sessions:
        msg_count = await db.get_message_count(s.id)
        result.append(SessionResponse(
            id=s.id,
            name=s.name,
            status=s.status,
            model=s.model,
            provider=s.provider,
            system_prompt=s.system_prompt,
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=msg_count,
        ))
    return result


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str):
    """Get session details with all messages."""
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await db.get_messages(session_id)
    msg_count = len(messages)

    return SessionDetailResponse(
        session=SessionResponse(
            id=session.id,
            name=session.name,
            status=session.status,
            model=session.model,
            provider=session.provider,
            system_prompt=session.system_prompt,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=msg_count,
        ),
        messages=[
            MessageResponse(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """Delete a session and all its messages."""
    deleted = await session_manager.remove_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/{session_id}/message", status_code=202)
async def send_message(
    session_id: str,
    body: MessageCreate,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None),
):
    """
    Send a user message to trigger the agent sampling loop.
    The API key can be passed as X-API-Key header or api_key query parameter.
    Returns immediately; use the SSE stream to monitor progress.
    """
    key = x_api_key or api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(
            status_code=400,
            detail="API key required. Pass as X-API-Key header, api_key query parameter, or set ANTHROPIC_API_KEY env var.",
        )

    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await session_manager.send_message(
        session_id=session_id,
        content=body.content,
        api_key=key,
    )

    return {"message": "Message sent, processing started", "session_id": session_id}


@router.post("/{session_id}/stop", response_model=StopResponse)
async def stop_session(session_id: str):
    """Stop the running agent loop for a session."""
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stopped = await session_manager.stop_session(session_id)
    if stopped:
        return StopResponse(message="Session stopped", session_id=session_id)
    return StopResponse(message="Session was not running", session_id=session_id)


@router.get("/{session_id}/events")
async def session_events(session_id: str):
    """
    Server-Sent Events stream for real-time session progress.
    Events: text, tool_use, tool_result, screenshot, error, status, done, keepalive
    """
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        async for event in session_manager.get_event_stream(session_id):
            yield {
                "event": event.get("event", "message"),
                "data": event.get("data", ""),
            }

    return EventSourceResponse(event_generator())
