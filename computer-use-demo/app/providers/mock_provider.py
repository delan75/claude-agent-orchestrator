import asyncio
import random
from typing import Any, Callable, Optional, List
import httpx
from anthropic.types.beta import (
    BetaContentBlockParam, 
    BetaMessageParam,
    BetaTextBlockParam,
    BetaToolUseBlockParam,
)
from computer_use_demo.tools import ToolResult, ToolVersion
from .base import BaseProvider

class MockProvider(BaseProvider):
    """
    Mock implementation of BaseProvider for demonstration purposes.
    Simulates agent behavior without calling any external APIs.
    """

    async def run_sampling_loop(
        self,
        model: str,
        system_prompt_suffix: str,
        messages: List[BetaMessageParam],
        output_callback: Callable[[BetaContentBlockParam], None],
        tool_output_callback: Callable[[ToolResult, str], None],
        api_response_callback: Callable[[httpx.Request, Optional[httpx.Response], Optional[Exception]], None],
        api_key: Optional[str] = None,
        only_n_most_recent_images: int = 3,
        max_tokens: int = 16384,
        tool_version: ToolVersion = "computer_use_20250124",
        thinking_budget: Optional[int] = None,
        token_efficient_tools_beta: bool = False,
    ) -> List[BetaMessageParam]:
        """
        Simulates a sequence of events: Thinking -> Tool Use -> Tool Result -> Text Response.
        Includes simulated latency and error triggers for robust system testing.
        """
        user_text = ""
        last_msg = messages[-1]
        if isinstance(last_msg["content"], str):
            user_text = last_msg["content"]
        elif isinstance(last_msg["content"], list):
            for block in last_msg["content"]:
                if block["type"] == "text":
                    user_text = block["text"]

        # Parse commands for demo scenarios
        force_error = "error" in user_text.lower()
        long_running = "wait" in user_text.lower()

        # 1. Simulate "Thinking" (Initial Latency for concurrency test)
        # 300ms basic latency, or 2s if long_running to allow cancellation
        initial_delay = 5.0 if long_running else 0.3
        await asyncio.sleep(initial_delay)

        output_callback({
            "type": "text",
            "text": "Analyzing request parameters..."
        })
        
        # 2. Simulate Tool Planning Latency
        await asyncio.sleep(1.0)

        # TRIGGER FAILURE SCENARIO
        if force_error:
            raise RuntimeError("Simulated infrastructure failure during tool execution.")

        # 3. Simulate Tool Use (Computer Screenshot)
        tool_id = f"mock_tool_{random.randint(1000, 9999)}"
        output_callback({
            "type": "tool_use",
            "name": "computer",
            "input": {"action": "screenshot"},
            "id": tool_id
        })
        
        # 4. Simulate Tool Execution Latency
        await asyncio.sleep(1.5)

        # 5. Simulate Tool Result
        mock_result = ToolResult(
            output="Screenshot captured successfully.",
            base64_image="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==" # 1x1 gray pixel
        )
        tool_output_callback(mock_result, tool_id)
        
        # 6. Simulate Final Processing Latency
        await asyncio.sleep(0.8)

        # 7. Simulate Final Text Response
        final_text = f"Screen analysis complete. I have successfully captured the desktop state and confirmed the system is operational. Awaiting further instructions."
        output_callback({
            "type": "text",
            "text": final_text
        })

        # Update message history
        new_messages = list(messages)
        new_messages.append({
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Analyzing request parameters..."},
                {"type": "tool_use", "name": "computer", "input": {"action": "screenshot"}, "id": tool_id},
            ]
        })
        new_messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": [{"type": "text", "text": "Screenshot captured successfully."}],
                }
            ]
        })
        new_messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": final_text}]
        })

        return new_messages
