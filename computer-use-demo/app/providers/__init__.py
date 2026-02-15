import os
from .base import BaseProvider
from .anthropic_provider import AnthropicProvider
from .mock_provider import MockProvider

def get_provider(provider_type: str = "anthropic") -> BaseProvider:
    """
    Factory function to get the appropriate provider.
    Checks USE_MOCK_AGENT environment variable to override with MockProvider.
    """
    if os.environ.get("USE_MOCK_AGENT", "false").lower() == "true":
        return MockProvider()
    
    return AnthropicProvider(provider_type)
