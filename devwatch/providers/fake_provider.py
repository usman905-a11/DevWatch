import time
from typing import Optional, Dict, List
from devwatch.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderCapabilities,
)
from devwatch.providers.exceptions import ProviderError, ProviderInvalidResponseError


class FakeLLMProvider(LLMProvider):
    """Fake LLM Provider for deterministic, fast offline testing without network access."""

    def __init__(
        self,
        default_content: str = "{}",
        canned_responses: Optional[Dict[str, str]] = None,
        forced_exception: Optional[Exception] = None,
        available: bool = True,
    ):
        self.default_content = default_content
        self.canned_responses = canned_responses or {}
        self.forced_exception = forced_exception
        self.available = available
        self.calls: List[LLMRequest] = []

    def is_available(self) -> bool:
        return self.available

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_streaming=True, supports_structured=True, max_context_tokens=128000)

    def _process_request(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)

        if self.forced_exception:
            raise self.forced_exception

        content = self.canned_responses.get(request.prompt, self.default_content)

        if not content:
            raise ProviderInvalidResponseError("Fake provider configured to return empty completion response.", provider="fake")

        prompt_tokens = len(request.prompt.split())
        completion_tokens = len(content.split())

        return LLMResponse(
            content=content,
            provider="fake_provider",
            model=request.model,
            latency_ms=1.5,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            request_id="fake_req_999",
        )

    def generate_completion_sync(self, request: LLMRequest) -> LLMResponse:
        return self._process_request(request)

    async def generate_completion(self, request: LLMRequest) -> LLMResponse:
        return self._process_request(request)
