"""
WebSocket endpoint for interactive chat sessions.
Provides bidirectional real-time communication as an alternative to SSE.
"""

import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import database as db
from ..session_manager import session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for interactive agent chat.

    Client sends JSON messages:
        {"type": "message", "content": "...", "api_key": "..."}
        {"type": "stop"}

    Server pushes JSON events:
        {"event": "text", "data": {...}}
        {"event": "tool_use", "data": {...}}
        {"event": "tool_result", "data": {...}}
        {"event": "error", "data": {...}}
        {"event": "status", "data": {...}}
        {"event": "done", "data": {...}}
    """
    # Verify session exists
    session = await db.get_session(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()

    state = await session_manager.get_or_create_state(session_id)

    # Task for reading events from the queue and sending to client
    async def _send_events():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(state.event_queue.get(), timeout=30.0)
                    await websocket.send_json(event)
                    if event.get("event") == "done":
                        break
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    await websocket.send_json({"event": "keepalive", "data": ""})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WebSocket send error: {e}")

    send_task: Optional[asyncio.Task] = None

    try:
        while True:
            # Receive message from client
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "event": "error",
                    "data": json.dumps({"message": "Invalid JSON"})
                })
                continue

            msg_type = data.get("type", "")

            if msg_type == "message":
                content = data.get("content", "").strip()
                api_key = data.get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")

                if not content:
                    await websocket.send_json({
                        "event": "error",
                        "data": json.dumps({"message": "Content is required"})
                    })
                    continue

                if not api_key:
                    await websocket.send_json({
                        "event": "error",
                        "data": json.dumps({"message": "API key is required"})
                    })
                    continue

                # Start event sender task
                if send_task and not send_task.done():
                    send_task.cancel()
                send_task = asyncio.create_task(_send_events())

                # Send message
                await session_manager.send_message(
                    session_id=session_id,
                    content=content,
                    api_key=api_key,
                    only_n_most_recent_images=data.get("only_n_most_recent_images", 3),
                    max_tokens=data.get("max_tokens", 16384),
                )

            elif msg_type == "stop":
                await session_manager.stop_session(session_id)
                await websocket.send_json({
                    "event": "status",
                    "data": json.dumps({"status": "stopped"})
                })

            else:
                await websocket.send_json({
                    "event": "error",
                    "data": json.dumps({"message": f"Unknown message type: {msg_type}"})
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}")
    finally:
        if send_task and not send_task.done():
            send_task.cancel()
