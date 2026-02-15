from typing import Any, Callable, Optional, List
import httpx
from anthropic.types.beta import BetaContentBlockParam, BetaMessageParam
from computer_use_demo.loop import sampling_loop, APIProvider
from computer_use_demo.tools import ToolResult, ToolVersion
from .base import BaseProvider

class AnthropicProvider(BaseProvider):
    """
    Implementation of BaseProvider using the real Anthropic/sampling_loop.
    """
    
    def __init__(self, provider_type: str = "anthropic"):
        try:
            self.provider = APIProvider(provider_type)
        except ValueError:
            self.provider = APIProvider.ANTHROPIC

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
        return await sampling_loop(
            model=model,
            provider=self.provider,
            system_prompt_suffix=system_prompt_suffix,
            messages=messages,
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
