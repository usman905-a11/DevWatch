from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMRequest(BaseModel):
    prompt: str
    system_prompt: str = ""
    model: str
    temperature: float = 0.2
    max_tokens: Optional[int] = None


class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    latency_ms: float
    usage: LLMUsage = Field(default_factory=LLMUsage)
    request_id: Optional[str] = None
    finish_reason: str = "unknown"


class LLMProvider(ABC):
    """Abstract Base Class for all LLM providers."""

    @abstractmethod
    async def generate_completion(self, request: LLMRequest) -> LLMResponse:
        """Asynchronously generate LLM completion."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if provider API key and configuration are available."""
        pass
