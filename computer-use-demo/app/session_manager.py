"""
Session Manager — orchestrates agent sessions with the Claude API sampling loop.

Each session has:
- An asyncio.Lock to prevent concurrent access to the same session
- An asyncio.Queue for pushing real-time events to SSE/WebSocket consumers
- In-memory message state that syncs with the database
"""

import asyncio
import json
import logging
import traceback
from typing import Any, Optional, cast

import httpx
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaMessageParam,
    BetaTextBlockParam,
    BetaToolResultBlockParam,
)

from computer_use_demo.loop import APIProvider, sampling_loop
from computer_use_demo.tools import ToolResult, ToolVersion

from . import database as db
from .models import SessionStatus

logger = logging.getLogger(__name__)

# Default model configs (mirrors streamlit.py but without streamlit dependency)
PROVIDER_TO_DEFAULT_MODEL: dict[str, str] = {
    "anthropic": "claude-sonnet-4-5-20250929",
    "bedrock": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "vertex": "claude-3-5-sonnet-v2@20241022",
}

MODEL_TO_TOOL_VERSION: dict[str, ToolVersion] = {
    "claude-opus-4-1-20250805": "computer_use_20250429",
    "claude-sonnet-4-20250514": "computer_use_20250429",
    "claude-opus-4-20250514": "computer_use_20250429",
    "claude-sonnet-4-5-20250929": "computer_use_20250124",
    "claude-haiku-4-5-20251001": "computer_use_20250124",
    "claude-opus-4-5-20251101": "computer_use_20251124",
}

DEFAULT_TOOL_VERSION: ToolVersion = "computer_use_20250124"


class SessionState:
    """In-memory state for a single session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.lock = asyncio.Lock()
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.messages: list[BetaMessageParam] = []
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def push_event(self, event: str, data: Any):
        """Push an event to the queue for SSE/WS consumers."""
        try:
            self.event_queue.put_nowait({
                "event": event,
                "data": data if isinstance(data, (str, int, float, bool)) else json.dumps(data, default=str),
            })
        except asyncio.QueueFull:
            # Drop oldest event if queue is full
            try:
                self.event_queue.get_nowait()
                self.event_queue.put_nowait({
                    "event": event,
                    "data": data if isinstance(data, (str, int, float, bool)) else json.dumps(data, default=str),
                })
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass


class SessionManager:
    """
    Manages all active agent sessions.
    Thread-safe via asyncio.Lock per session.
    """

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._global_lock = asyncio.Lock()

    async def get_or_create_state(self, session_id: str) -> SessionState:
        """Get or create in-memory state for a session."""
        async with self._global_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionState(session_id)
                # Load existing messages from database
                db_messages = await db.get_messages(session_id)
                for msg in db_messages:
                    self._sessions[session_id].messages.append({
                        "role": msg.role,
                        "content": msg.content,
                    })
            return self._sessions[session_id]

    async def create_session(
        self,
        name: str = "Untitled Session",
        model: str = "claude-sonnet-4-5-20250929",
        provider: str = "anthropic",
        system_prompt: str = "",
    ) -> str:
        """Create a new session and return its ID."""
        session = await db.create_session(
            name=name, model=model, provider=provider, system_prompt=system_prompt
        )
        # Initialize in-memory state
        await self.get_or_create_state(session.id)
        return session.id

    async def send_message(
        self,
        session_id: str,
        content: str,
        api_key: str,
        only_n_most_recent_images: int = 3,
        tool_version: Optional[ToolVersion] = None,
        max_tokens: int = 16384,
        thinking_budget: Optional[int] = None,
        token_efficient_tools_beta: bool = False,
    ) -> None:
        """
        Send a user message and start the agent sampling loop.
        Events are pushed to the session's event queue for SSE/WS consumers.
        """
        state = await self.get_or_create_state(session_id)

        async with state.lock:
            if state.running:
                await state.push_event("error", {"message": "Session is already processing a message"})
                return

            state.running = True

        # Get session config from database
        session = await db.get_session(session_id)
        if not session:
            await state.push_event("error", {"message": "Session not found"})
            return

        model = session.model
        provider_str = session.provider
        system_prompt = session.system_prompt or ""

        # Determine tool version from model if not specified
        if tool_version is None:
            tool_version = MODEL_TO_TOOL_VERSION.get(model, DEFAULT_TOOL_VERSION)

        from .providers import get_provider
        provider_instance = get_provider(provider_str)

        # Add the user message
        user_message: BetaMessageParam = {
            "role": "user",
            "content": [BetaTextBlockParam(type="text", text=content)],
        }
        state.messages.append(user_message)

        # Save user message to database
        await db.save_message(session_id, "user", user_message["content"])
        await db.update_session_status(session_id, SessionStatus.RUNNING)
        await state.push_event("status", {"status": "running"})

        # Define callbacks for the sampling loop
        def output_callback(content_block: BetaContentBlockParam):
            """Called for each content block in the assistant response."""
            if isinstance(content_block, dict):
                block_type = content_block.get("type", "unknown")
                if block_type == "text":
                    asyncio.create_task(state.push_event("text", {
                        "type": "text",
                        "text": content_block.get("text", ""),
                    }))
                elif block_type == "tool_use":
                    asyncio.create_task(state.push_event("tool_use", {
                        "type": "tool_use",
                        "name": content_block.get("name", ""),
                        "input": content_block.get("input", {}),
                        "id": content_block.get("id", ""),
                    }))
                elif block_type == "thinking":
                    asyncio.create_task(state.push_event("thinking", {
                        "type": "thinking",
                        "thinking": content_block.get("thinking", ""),
                    }))

        def tool_output_callback(result: ToolResult, tool_id: str):
            """Called when a tool produces output."""
            event_data: dict[str, Any] = {
                "tool_id": tool_id,
                "type": "tool_result",
            }
            if result.output:
                event_data["output"] = result.output
            if result.error:
                event_data["error"] = result.error
            if result.base64_image:
                event_data["screenshot"] = result.base64_image
            asyncio.create_task(state.push_event("tool_result", event_data))

        def api_response_callback(
            request: httpx.Request,
            response: httpx.Response | object | None,
            error: Exception | None,
        ):
            """Called after each API response."""
            if error:
                asyncio.create_task(state.push_event("error", {
                    "message": str(error),
                    "type": error.__class__.__name__,
                }))

        # Run the sampling loop as a background task
        async def _run_loop():
            try:
                result_messages = await provider_instance.run_sampling_loop(
                    model=model,
                    system_prompt_suffix=system_prompt,
                    messages=state.messages,
                    output_callback=output_callback,
                    tool_output_callback=tool_output_callback,
                    api_response_callback=api_response_callback,
                    api_key=api_key,
                    only_n_most_recent_images=only_n_most_recent_images,
                    max_tokens=max_tokens,
                    tool_version=tool_version,
                    thinking_budget=thinking_budget,
                    token_efficient_tools_beta=token_efficient_tools_beta,
                )
                state.messages = result_messages

                # Persist all messages to database
                messages_to_save = []
                for msg in state.messages:
                    messages_to_save.append({
                        "role": msg.get("role", "unknown"),
                        "content": msg.get("content", ""),
                    })
                await db.save_messages_bulk(session_id, messages_to_save)
                await db.update_session_status(session_id, SessionStatus.IDLE)
                await state.push_event("status", {"status": "idle"})
                await state.push_event("done", {"message": "Agent loop completed"})

            except asyncio.CancelledError:
                await db.update_session_status(session_id, SessionStatus.STOPPED)
                await state.push_event("status", {"status": "stopped"})
                await state.push_event("done", {"message": "Agent loop cancelled"})
            except Exception as e:
                logger.error(f"Error in sampling loop for session {session_id}: {e}")
                logger.error(traceback.format_exc())
                await db.update_session_status(session_id, SessionStatus.ERROR)
                await state.push_event("error", {
                    "message": str(e),
                    "type": e.__class__.__name__,
                })
                await state.push_event("done", {"message": "Agent loop failed"})
            finally:
                async with state.lock:
                    state.running = False

        state._task = asyncio.create_task(_run_loop())

    async def stop_session(self, session_id: str) -> bool:
        """Stop the running agent loop for a session."""
        state = await self.get_or_create_state(session_id)
        if state._task and not state._task.done():
            state._task.cancel()
            return True
        return False

    async def remove_session(self, session_id: str) -> bool:
        """Remove session from memory and database."""
        # Stop if running
        await self.stop_session(session_id)

        async with self._global_lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

        return await db.delete_session(session_id)

    async def get_event_stream(self, session_id: str):
        """
        Async generator that yields SSE events for a session.
        Used by the SSE endpoint.
        """
        state = await self.get_or_create_state(session_id)

        # Send initial status
        session = await db.get_session(session_id)
        if session:
            yield {
                "event": "status",
                "data": json.dumps({"status": session.status.value}),
            }

        while True:
            try:
                event = await asyncio.wait_for(state.event_queue.get(), timeout=30.0)
                yield event
                if event.get("event") == "done":
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                yield {"event": "keepalive", "data": ""}
            except Exception:
                break


# Global session manager instance
session_manager = SessionManager()
