import os
import time
import logging
from typing import Optional, Dict, Any

from devwatch.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderCapabilities,
)
from devwatch.providers.exceptions import (
    ProviderError,
    ProviderAuthenticationError,
    ProviderAuthorizationError,
    ProviderRateLimitError,
    ProviderQuotaExhaustedError,
    ProviderTimeoutError,
    ProviderTemporaryError,
    ProviderInvalidResponseError,
    ProviderContextLengthError,
    ProviderContentPolicyError,
    ProviderConfigurationError,
    ProviderNonRetryableError,
)

logger = logging.getLogger("devwatch.providers.openai")


class OpenAIProviderAdapter(LLMProvider):
    """Adapter wrapping OpenAI / OpenRouter SDK with typed error translation and metric tracking."""

    def __init__(self, provider_name: str = "openrouter"):
        self.provider_name = provider_name

    def is_available(self) -> bool:
        return bool(
            os.getenv("OPENROUTER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("GROQ_API_KEY")
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_streaming=True, supports_structured=True, max_context_tokens=128000)

    def _get_client_config(self) -> Dict[str, Any]:

        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            headers = {
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://github.com/devwatch"),
                "X-Title": os.getenv("OPENROUTER_SITE_NAME", "DevWatch"),
            }
            return {
                "api_key": openrouter_key,
                "base_url": base_url,
                "default_headers": headers,
            }

        api_key = (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("GROQ_API_KEY")
        )
        if not api_key:
            raise ProviderConfigurationError("No valid LLM provider API key found in environment.")

        kwargs: Dict[str, Any] = {"api_key": api_key}
        if os.getenv("OPENAI_BASE_URL"):
            kwargs["base_url"] = os.getenv("OPENAI_BASE_URL")
        return kwargs

    def _translate_sdk_error(self, err: Exception) -> ProviderError:
        err_str = str(err).lower()
        err_type = type(err).__name__

        if "authenticationerror" in err_type.lower() or "invalid api key" in err_str:
            return ProviderAuthenticationError("Authentication failed: Invalid API key", provider=self.provider_name, raw_error=err)
        
        if "permissiondeniederror" in err_type.lower() or "forbidden" in err_str:
            return ProviderAuthorizationError("Authorization failed: Access denied for model", provider=self.provider_name, raw_error=err)

        if "ratelimiterror" in err_type.lower() or "429" in err_str:
            if "free-models-per-day" in err_str or "quota" in err_str or "limit reached" in err_str:
                return ProviderQuotaExhaustedError(
                    "Daily free rate limit reached (50/50 requests used today). Please wait for daily reset or add credits.",
                    provider=self.provider_name,
                    raw_error=err,
                )
            return ProviderRateLimitError("Provider rate limit exceeded. Please retry later.", provider=self.provider_name, raw_error=err)

        if "timeout" in err_type.lower() or "timed out" in err_str:
            return ProviderTimeoutError("Request to LLM provider timed out.", provider=self.provider_name, raw_error=err)

        if "connectionerror" in err_type.lower() or "internalservererror" in err_type.lower() or "502" in err_str or "503" in err_str:
            return ProviderTemporaryError("Temporary provider server error.", provider=self.provider_name, raw_error=err)

        if "badrequesterror" in err_type.lower():
            if "context_length" in err_str or "maximum context length" in err_str or "too long" in err_str:
                return ProviderContextLengthError("Input prompt exceeded model maximum context length.", provider=self.provider_name, raw_error=err)
            return ProviderNonRetryableError(f"Bad request error: {str(err)}", provider=self.provider_name, raw_error=err)

        return ProviderError(f"LLM Provider Error: {str(err)}", provider=self.provider_name, raw_error=err)

    def generate_completion_sync(self, request: LLMRequest) -> LLMResponse:
        if not self.is_available():
            raise ProviderConfigurationError("No valid LLM provider API key configured.")

        config = self._get_client_config()
        start_time = time.time()

        try:
            import openai
            client = openai.OpenAI(**config)
            response = client.chat.completions.create(
                model=request.model,
                messages=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.prompt},
                ],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            latency_ms = (time.time() - start_time) * 1000

            if not response.choices or not response.choices[0].message.content:
                raise ProviderInvalidResponseError("Provider returned an empty completion response.", provider=self.provider_name)

            content = response.choices[0].message.content
            usage = LLMUsage()
            if hasattr(response, "usage") and response.usage:
                usage = LLMUsage(
                    prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(response.usage, "total_tokens", 0) or 0,
                )

            req_id = getattr(response, "id", None)
            return LLMResponse(
                content=content,
                provider=self.provider_name,
                model=request.model,
                latency_ms=latency_ms,
                usage=usage,
                request_id=req_id,
            )
        except ProviderError:
            raise
        except Exception as err:
            raise self._translate_sdk_error(err)

    async def generate_completion(self, request: LLMRequest) -> LLMResponse:
        if not self.is_available():
            raise ProviderConfigurationError("No valid LLM provider API key configured.")

        config = self._get_client_config()
        start_time = time.time()

        try:
            import openai
            client = openai.AsyncOpenAI(**config)
            response = await client.chat.completions.create(
                model=request.model,
                messages=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.prompt},
                ],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            latency_ms = (time.time() - start_time) * 1000

            if not response.choices or not response.choices[0].message.content:
                raise ProviderInvalidResponseError("Provider returned an empty completion response.", provider=self.provider_name)

            content = response.choices[0].message.content
            usage = LLMUsage()
            if hasattr(response, "usage") and response.usage:
                usage = LLMUsage(
                    prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(response.usage, "total_tokens", 0) or 0,
                )

            req_id = getattr(response, "id", None)
            return LLMResponse(
                content=content,
                provider=self.provider_name,
                model=request.model,
                latency_ms=latency_ms,
                usage=usage,
                request_id=req_id,
            )
        except ProviderError:
            raise
        except Exception as err:
            raise self._translate_sdk_error(err)
