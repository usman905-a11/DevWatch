import os
import time
import asyncio
import logging
import httpx
from typing import Optional, Dict, Any

from devwatch.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
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
    """Adapter for Gemini and other OpenAI-compatible chat APIs."""

    def __init__(
        self,
        provider_name: str = "gemini",
        max_concurrency: int = 3,
        request_delay: float = 0.5,
    ):
        self.provider_name = provider_name
        self.max_concurrency = max_concurrency
        if not 1 <= max_concurrency <= 3:
            raise ValueError("Provider concurrency must be between one and three")
        self.request_delay = request_delay
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    def is_available(self) -> bool:
        if self.provider_name == "gemini":
            return bool(os.getenv("GEMINI_API_KEY"))
        return bool(
            os.getenv("OPENROUTER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )

    def _get_httpx_async_client(self) -> httpx.AsyncClient:
        # SSL verification toggle: DEVWATCH_SSL_VERIFY (default True unless set to false/0)
        ssl_verify_env = os.getenv("DEVWATCH_SSL_VERIFY", "true").lower()
        verify_ssl = ssl_verify_env not in ("false", "0", "no", "off")

        return httpx.AsyncClient(
            verify=verify_ssl,
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    def _get_client_config(self) -> Dict[str, Any]:
        if self.provider_name == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ProviderConfigurationError("GEMINI_API_KEY is required for Gemini models.")
            return {
                "api_key": api_key,
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "http_client": self._get_httpx_async_client(),
                "max_retries": 0,
            }

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
                "max_retries": 0,
                "http_client": self._get_httpx_async_client(),
            }

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderConfigurationError("No valid LLM provider API key found in environment.")

        kwargs: Dict[str, Any] = {
            "api_key": api_key,
            "max_retries": 0,
            "http_client": self._get_httpx_async_client(),
        }
        if os.getenv("OPENAI_BASE_URL"):
            kwargs["base_url"] = os.getenv("OPENAI_BASE_URL")
        return kwargs

    def _translate_sdk_error(self, err: Exception) -> ProviderError:
        err_str = str(err).lower()
        err_type = type(err).__name__
        status_code = getattr(err, "status_code", None)
        if status_code is None and hasattr(err, "response") and getattr(err, "response") is not None:
            status_code = getattr(err.response, "status_code", None)

        logger.error(
            f"Provider Error [{err_type}] HTTP Status: {status_code or 'N/A'} for provider '{self.provider_name}'"
        )

        if status_code == 401 or "authenticationerror" in err_type.lower() or "invalid api key" in err_str or "unauthorized" in err_str:
            return ProviderAuthenticationError("Authentication failed: Invalid API key", provider=self.provider_name, raw_error=err)
        
        if status_code == 403 or "permissiondeniederror" in err_type.lower() or "forbidden" in err_str:
            return ProviderAuthorizationError("Authorization failed: Access denied for model", provider=self.provider_name, raw_error=err)

        if status_code == 429 or "ratelimiterror" in err_type.lower() or "429" in err_str:
            if "free-models-per-day" in err_str or "quota" in err_str or "limit reached" in err_str or "exceeded your current quota" in err_str:
                return ProviderQuotaExhaustedError(
                    "Daily rate/quota limit reached. Please wait for reset or add credits.",
                    provider=self.provider_name,
                    raw_error=err,
                )
            return ProviderRateLimitError("Provider rate limit exceeded. Please retry later.", provider=self.provider_name, raw_error=err)

        if status_code in (408, 504) or "timeout" in err_type.lower() or "timed out" in err_str:
            return ProviderTimeoutError("Request to LLM provider timed out.", provider=self.provider_name, raw_error=err)

        if (
            status_code in (500, 502, 503)
            or "connectionerror" in err_type.lower()
            or "connecterror" in err_type.lower()
            or "networkerror" in err_type.lower()
            or "transporterror" in err_type.lower()
            or "internalservererror" in err_type.lower()
            or "502" in err_str
            or "503" in err_str
            or "connection reset" in err_str
            or "socket" in err_str
        ):
            return ProviderTemporaryError("Temporary provider connection/server error.", provider=self.provider_name, raw_error=err)

        if status_code == 400 or "badrequesterror" in err_type.lower():
            if "context_length" in err_str or "maximum context length" in err_str or "too long" in err_str:
                return ProviderContextLengthError("Input prompt exceeded model maximum context length.", provider=self.provider_name, raw_error=err)
            return ProviderNonRetryableError(f"Bad request error", provider=self.provider_name, raw_error=err)

        return ProviderError(f"LLM Provider Error: [{err_type}]", provider=self.provider_name, raw_error=err)

    def _completion_options(self, request: LLMRequest) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.prompt},
            ],
            "max_tokens": request.max_tokens,
        }
        if self.provider_name != "gemini":
            options["temperature"] = request.temperature
        if request.json_mode:
            options["response_format"] = {"type": "json_object"}
        # Gemini's documented compatibility control; do not send unsupported
        # reasoning options to older non-reasoning OpenAI-compatible models.
        if self.provider_name == "gemini" and request.reasoning_effort is not None:
            options["reasoning_effort"] = request.reasoning_effort
        return options

    async def generate_completion(self, request: LLMRequest) -> LLMResponse:
        if not self.is_available():
            detail = (
                "GEMINI_API_KEY is required for Gemini models."
                if self.provider_name == "gemini"
                else "No valid LLM provider API key configured."
            )
            raise ProviderConfigurationError(detail)

        config = None
        client = None
        start_time = time.time()

        async with self.semaphore:
            try:
                config = self._get_client_config()
                if self.request_delay > 0:
                    await asyncio.sleep(self.request_delay)
                import openai
                client = openai.AsyncOpenAI(**config)
                response = await client.chat.completions.create(
                    **self._completion_options(request)
                )

                latency_ms = (time.time() - start_time) * 1000

                if not response.choices:
                    raise ProviderInvalidResponseError("Provider returned an empty completion response.", provider=self.provider_name)

                content = response.choices[0].message.content or ""
                usage = LLMUsage()
                if hasattr(response, "usage") and response.usage:
                    usage = LLMUsage(
                        prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                        completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                        total_tokens=getattr(response.usage, "total_tokens", 0) or 0,
                        reasoning_tokens=getattr(getattr(response.usage, "completion_tokens_details", None),
                                                 "reasoning_tokens", None),
                        cached_prompt_tokens=getattr(getattr(response.usage, "prompt_tokens_details", None),
                                                     "cached_tokens", None),
                    )

                req_id = getattr(response, "id", None)
                return LLMResponse(
                    content=content,
                    provider=self.provider_name,
                    model=request.model,
                    latency_ms=latency_ms,
                    usage=usage,
                    request_id=req_id,
                    finish_reason=response.choices[0].finish_reason or "unknown",
                    refusal=bool(getattr(response.choices[0].message, "refusal", None)),
                )
            except ProviderError:
                raise
            except Exception as err:
                raise self._translate_sdk_error(err)
            finally:
                transport = config.get("http_client") if config else None
                if client is not None:
                    await self._close_transport(client.close())
                elif transport is not None:
                    await self._close_transport(transport.aclose())

    @staticmethod
    async def _close_transport(closing):
        cleanup = asyncio.create_task(closing)
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError
