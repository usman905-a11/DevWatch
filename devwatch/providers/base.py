from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMRequest(BaseModel):
    prompt: str
    system_prompt: str = "You are an expert AI code auditor."
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_tokens: Optional[int] = None


class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    latency_ms: float
    usage: LLMUsage = Field(default_factory=LLMUsage)
    request_id: Optional[str] = None


class ProviderCapabilities(BaseModel):
    supports_streaming: bool = False
    supports_structured: bool = True
    max_context_tokens: int = 128000


class LLMProvider(ABC):
    """Abstract Base Class for all LLM providers."""

    @abstractmethod
    def generate_completion_sync(self, request: LLMRequest) -> LLMResponse:
        """Synchronously generate LLM completion."""
        pass

    @abstractmethod
    async def generate_completion(self, request: LLMRequest) -> LLMResponse:
        """Asynchronously generate LLM completion."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if provider API key and configuration are available."""
        pass

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Return capabilities supported by this provider."""
        pass

