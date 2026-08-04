import os
from typing import Optional
from devwatch.providers.base import LLMProvider
from devwatch.providers.openai_adapter import OpenAIProviderAdapter
from devwatch.providers.fake_provider import FakeLLMProvider

_active_provider: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """Return configured active LLM provider singleton or instance."""
    global _active_provider
    if _active_provider is not None:
        return _active_provider

    # Default to OpenAI / OpenRouter adapter
    _active_provider = OpenAIProviderAdapter()
    return _active_provider


def set_provider(provider: Optional[LLMProvider]) -> None:
    """Override default LLM provider (e.g. for testing with FakeLLMProvider)."""
    global _active_provider
    _active_provider = provider


def reset_provider() -> None:
    """Reset active LLM provider to default."""
    global _active_provider
    _active_provider = None
