import time
import asyncio
import pytest
from unittest.mock import patch, MagicMock
from devwatch.config import Config
from devwatch.providers.base import LLMRequest, LLMResponse, LLMUsage
from devwatch.resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenError
from devwatch.resilience.manager import ResilienceManager, resilience_manager
from devwatch.providers.exceptions import (
    ProviderError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitError,
    ProviderAuthenticationError,
    ProviderTemporaryError,
    ProviderContextLengthError,
)


@pytest.fixture(autouse=True)
def reset_resilience_state():
    resilience_manager.circuit_breakers.clear()
    resilience_manager.job_token_usage.clear()
    yield
    resilience_manager.circuit_breakers.clear()
    resilience_manager.job_token_usage.clear()


@pytest.mark.asyncio
async def test_concurrency_limit_enforcement():
    manager = ResilienceManager()
    manager.semaphore = asyncio.Semaphore(2)

    active_count = 0
    max_observed_active = 0

    async def mock_worker(req):
        nonlocal active_count, max_observed_active
        active_count += 1
        max_observed_active = max(max_observed_active, active_count)
        await asyncio.sleep(0.05)
        active_count -= 1
        return LLMResponse(content="ok", provider="test", model="m", latency_ms=1.0)

    req = LLMRequest(prompt="test")
    tasks = [manager.execute_with_resilience(mock_worker, req, provider_name="test_provider") for _ in range(5)]
    await asyncio.gather(*tasks)

    assert max_observed_active <= 2


@pytest.mark.asyncio
async def test_quota_exhaustion_zero_retries():
    manager = ResilienceManager()
    call_count = 0

    async def mock_failing_func(req):
        nonlocal call_count
        call_count += 1
        raise ProviderQuotaExhaustedError("Daily limit reached", provider="test")

    req = LLMRequest(prompt="test")

    with pytest.raises(ProviderQuotaExhaustedError):
        await manager.execute_with_resilience(mock_failing_func, req, provider_name="test", max_retries=3)

    # Must fail on exact 1st attempt with 0 retries
    assert call_count == 1


@pytest.mark.asyncio
async def test_transient_error_exponential_backoff_and_retry_success():
    manager = ResilienceManager()
    call_count = 0

    async def mock_flaky_func(req):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ProviderTemporaryError("503 Service Unavailable", provider="test")
        return LLMResponse(content="success", provider="test", model="m", latency_ms=1.0)

    req = LLMRequest(prompt="test")
    res = await manager.execute_with_resilience(
        mock_flaky_func, req, provider_name="test", max_retries=3, base_backoff=0.01, jitter=0.001
    )

    assert res.content == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_circuit_breaker_state_transitions():
    cb = CircuitBreaker(provider_name="test_cb", failure_threshold=2, recovery_timeout=0.1)

    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True

    # Record 2 failures -> trips to OPEN
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # While OPEN and within recovery timeout, requests are rejected immediately
    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        cb.allow_request()
    assert "OPEN due to repeated failures" in str(exc_info.value)


    # Wait for recovery timeout
    await asyncio.sleep(0.12)

    # Probe request allowed -> transitions to HALF_OPEN
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    # Probe succeeds -> transitions back to CLOSED
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_job_token_budget_exceeded():
    manager = ResilienceManager()

    async def mock_func(req):
        return LLMResponse(
            content="tokens",
            provider="test",
            model="m",
            latency_ms=1.0,
            usage=LLMUsage(prompt_tokens=100, completion_tokens=100, total_tokens=200),
        )

    req = LLMRequest(prompt="test")

    with patch.object(Config, "MAX_JOB_TOKEN_BUDGET", 300):
        # Call 1: 200 tokens -> passes
        await manager.execute_with_resilience(mock_func, req, job_id="job_99")

        # Call 2: +200 tokens = 400 > 300 -> raises ProviderError
        with pytest.raises(ProviderError) as exc_info:
            await manager.execute_with_resilience(mock_func, req, job_id="job_99")
        assert "Job token budget exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_global_review_deadline_exceeded(tmp_path):
    from devwatch.pipeline.dag import ReviewPipeline
    (tmp_path / "app.py").write_text("x = 1")

    pipeline = ReviewPipeline()

    with patch("devwatch.agents.llm.is_llm_available", return_value=False):
        with patch.object(Config, "GLOBAL_REVIEW_TIMEOUT_SECONDS", 0.001):
            with pytest.raises(TimeoutError) as exc_info:
                await pipeline.execute(str(tmp_path))
            assert "Global review execution deadline" in str(exc_info.value)
