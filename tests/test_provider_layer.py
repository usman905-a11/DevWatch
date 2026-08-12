import pytest
from unittest.mock import patch, MagicMock
from devwatch.providers.base import LLMRequest, LLMResponse, LLMUsage
from devwatch.providers.fake_provider import FakeLLMProvider
from devwatch.providers.openai_adapter import OpenAIProviderAdapter
from devwatch.providers.factory import set_provider, reset_provider, get_provider
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
    ProviderConfigurationError,
    ProviderNonRetryableError,
)
from devwatch.agents import llm


@pytest.fixture(autouse=True)
def cleanup_provider_factory():
    reset_provider()
    yield
    reset_provider()


@pytest.mark.asyncio
async def test_successful_completion_with_usage_metadata():
    fake = FakeLLMProvider(default_content="Hello world")
    set_provider(fake)

    req = LLMRequest(prompt="Say hi", model="test-model")
    res = await fake.generate_completion(req)

    assert res.content == "Hello world"
    assert res.provider == "fake_provider"
    assert res.usage.prompt_tokens > 0
    assert res.usage.completion_tokens > 0
    assert res.usage.total_tokens == res.usage.prompt_tokens + res.usage.completion_tokens
    assert res.latency_ms > 0
    assert res.request_id == "fake_req_999"


@pytest.mark.asyncio
async def test_invalid_credentials_exception():
    fake = FakeLLMProvider(forced_exception=ProviderAuthenticationError("Invalid key", provider="test"))
    set_provider(fake)

    with pytest.raises(ProviderAuthenticationError) as exc_info:
        await fake.generate_completion(LLMRequest(prompt="test"))
    assert "Invalid key" in str(exc_info.value)


@pytest.mark.asyncio
async def test_429_rate_limit_exception():
    fake = FakeLLMProvider(forced_exception=ProviderRateLimitError("Rate limit exceeded", provider="test"))
    set_provider(fake)

    with pytest.raises(ProviderRateLimitError) as exc_info:
        await fake.generate_completion(LLMRequest(prompt="test"))
    assert "Rate limit exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_daily_quota_exhaustion_exception():
    fake = FakeLLMProvider(forced_exception=ProviderQuotaExhaustedError("Quota exhausted", provider="test"))
    set_provider(fake)

    with pytest.raises(ProviderQuotaExhaustedError) as exc_info:
        await fake.generate_completion(LLMRequest(prompt="test"))
    assert "Quota exhausted" in str(exc_info.value)


@pytest.mark.asyncio
async def test_timeout_exception():
    fake = FakeLLMProvider(forced_exception=ProviderTimeoutError("Connection timed out", provider="test"))
    set_provider(fake)

    with pytest.raises(ProviderTimeoutError) as exc_info:
        await fake.generate_completion(LLMRequest(prompt="test"))
    assert "timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_temporary_provider_error():
    fake = FakeLLMProvider(forced_exception=ProviderTemporaryError("503 Service Unavailable", provider="test"))
    set_provider(fake)

    with pytest.raises(ProviderTemporaryError) as exc_info:
        await fake.generate_completion(LLMRequest(prompt="test"))
    assert "503" in str(exc_info.value)


@pytest.mark.asyncio
async def test_empty_completion_exception():
    fake = FakeLLMProvider(default_content="")
    set_provider(fake)

    with pytest.raises(ProviderInvalidResponseError):
        await fake.generate_completion(LLMRequest(prompt="test"))


@pytest.mark.asyncio
async def test_context_length_exceeded_exception():
    fake = FakeLLMProvider(forced_exception=ProviderContextLengthError("Context window exceeded", provider="test"))
    set_provider(fake)

    with pytest.raises(ProviderContextLengthError):
        await fake.generate_completion(LLMRequest(prompt="test"))


def test_provider_configuration_failure(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    adapter = OpenAIProviderAdapter()
    assert adapter.is_available() is False


    with pytest.raises(ProviderConfigurationError):
        adapter.generate_completion_sync(LLMRequest(prompt="test"))


def test_openai_adapter_sdk_exception_translation():
    adapter = OpenAIProviderAdapter(provider_name="openrouter")

    # Create dummy exceptions
    err_auth = type("AuthenticationError", (Exception,), {})("Invalid API key")
    err_rate = type("RateLimitError", (Exception,), {})("free-models-per-day limit reached")
    err_timeout = type("APITimeoutError", (Exception,), {})("Timed out")

    translated_auth = adapter._translate_sdk_error(err_auth)
    assert isinstance(translated_auth, ProviderAuthenticationError)

    translated_rate = adapter._translate_sdk_error(err_rate)
    assert isinstance(translated_rate, ProviderQuotaExhaustedError)

    translated_timeout = adapter._translate_sdk_error(err_timeout)
    assert isinstance(translated_timeout, ProviderTimeoutError)
