from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, List
import httpx
from anthropic.types.beta import BetaContentBlockParam, BetaMessageParam
from computer_use_demo.tools import ToolResult, ToolVersion

class BaseProvider(ABC):
    """
    Abstract base class for LLM providers.
    Provides a unified interface for running the agent sampling loop.
    """
    
    @abstractmethod
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
        Runs the agent sampling loop and returns the updated conversation history.
        """
        pass
