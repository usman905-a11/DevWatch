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
    """Adapter wrapping Groq / OpenAI compatible API with typed error translation, metric tracking, and connection throttling."""

    def __init__(
        self,
        provider_name: str = "groq",
        max_concurrency: int = 2,
        request_delay: float = 0.5,
    ):
        self.provider_name = provider_name
        self.max_concurrency = int(os.getenv("DEVWATCH_MAX_CONCURRENT_LLM", str(max_concurrency)))
        self.request_delay = float(os.getenv("DEVWATCH_LLM_REQUEST_DELAY", str(request_delay)))
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    def is_available(self) -> bool:
        return bool(
            os.getenv("GROQ_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_streaming=True, supports_structured=True, max_context_tokens=32768)

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
        # Groq API support (OpenAI-compatible)
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
            return {
                "api_key": groq_key,
                "base_url": base_url,
                "http_client": self._get_httpx_async_client(),
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
                "http_client": self._get_httpx_async_client(),
            }

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderConfigurationError("No valid Groq (GROQ_API_KEY) or LLM provider API key found in environment.")

        kwargs: Dict[str, Any] = {
            "api_key": api_key,
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

    def generate_completion_sync(self, request: LLMRequest) -> LLMResponse:
        if not self.is_available():
            raise ProviderConfigurationError("No valid LLM provider API key configured.")

        config = self._get_client_config()
        if "http_client" in config and isinstance(config["http_client"], httpx.AsyncClient):
            del config["http_client"]

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

        async with self.semaphore:
            if self.request_delay > 0:
                await asyncio.sleep(self.request_delay)

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
