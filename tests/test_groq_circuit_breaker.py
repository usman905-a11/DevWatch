import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from devwatch.config import Config
from devwatch.providers.exceptions import (
    ProviderError,
    CircuitBreakerOpenError,
    ProviderQuotaExhaustedError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
)
from devwatch.providers.base import LLMRequest, LLMResponse, LLMUsage
from devwatch.resilience.circuit_breaker import CircuitBreaker, CircuitState
from devwatch.resilience.manager import ResilienceManager, resilience_manager
from devwatch.agents.llm import acall_llm_structured
from devwatch.pipeline.context import ReviewContext, ReviewOutcome
from devwatch.pipeline.dag import ReviewPipeline
from devwatch.models import StructuredCodeIssue, StructuredSecurityResponse
from devwatch.server import lifespan, active_review_tasks, app


@pytest.fixture(autouse=True)
def reset_resilience_manager():
    resilience_manager.circuit_breakers.clear()
    yield
    resilience_manager.circuit_breakers.clear()


@pytest.mark.asyncio
async def test_open_circuit_causes_zero_retries_and_zero_calls():
    rm = ResilienceManager()
    cb = rm.get_circuit_breaker("groq")
    cb.state = CircuitState.OPEN
    cb.last_state_change = 9999999999.0  # Far in the future so circuit remains OPEN

    mock_func = AsyncMock()
    req = LLMRequest(prompt="test prompt", model="llama-3.3-70b-versatile")

    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        await rm.execute_with_resilience(mock_func, req, provider_name="groq")

    assert "OPEN due to repeated failures" in str(exc_info.value)
    # Proves 0 calls to underlying provider when circuit is open
    assert mock_func.call_count == 0


@pytest.mark.asyncio
async def test_quota_and_auth_errors_cause_zero_retries():
    rm = ResilienceManager()
    
    # 1. Quota error
    mock_quota_func = AsyncMock(side_effect=ProviderQuotaExhaustedError("Quota reached"))
    req = LLMRequest(prompt="test", model="llama-3.3-70b-versatile")

    with pytest.raises(ProviderQuotaExhaustedError):
        await rm.execute_with_resilience(mock_quota_func, req, provider_name="groq_quota_test")

    assert mock_quota_func.call_count == 1  # 0 retries

    # 2. Auth error
    mock_auth_func = AsyncMock(side_effect=ProviderAuthenticationError("Invalid Groq API Key"))
    with pytest.raises(ProviderAuthenticationError):
        await rm.execute_with_resilience(mock_auth_func, req, provider_name="groq_auth_test")

    assert mock_auth_func.call_count == 1  # 0 retries


@pytest.mark.asyncio
async def test_invalid_structured_output_receives_bounded_repair_attempts():
    fake_provider = MagicMock()
    fake_provider.is_available.return_value = True

    # 1. Schema invalid completion receives max_retries attempts
    mock_completion = AsyncMock(return_value="NOT_VALID_JSON")
    with patch("devwatch.agents.llm.acall_llm_completion", mock_completion):
        res = await acall_llm_structured(
            prompt="audit code",
            response_model=StructuredSecurityResponse,
            max_retries=3,
            provider=fake_provider,
        )

        assert res is None
        assert mock_completion.call_count == 3

    # 2. Provider exception stops repair attempts immediately (0 repair retries)
    mock_failing_completion = AsyncMock(side_effect=CircuitBreakerOpenError("Circuit open"))
    with patch("devwatch.agents.llm.acall_llm_completion", mock_failing_completion):
        with pytest.raises(CircuitBreakerOpenError):
            await acall_llm_structured(
                prompt="audit code",
                response_model=StructuredSecurityResponse,
                max_retries=3,
                provider=fake_provider,
            )

        assert mock_failing_completion.call_count == 1


@pytest.mark.asyncio
async def test_one_provider_failure_does_not_discard_completed_results(tmp_path):
    (tmp_path / "app.py").write_text("import os\nAWS_SECRET_ACCESS_KEY = 'AKIA1234567890ABCDEF1234'\n")

    pipeline = ReviewPipeline()
    # Mock security agent raising CircuitBreakerOpenError
    pipeline.security_agent.execute = AsyncMock(side_effect=CircuitBreakerOpenError("Groq Circuit Open"))
    pipeline.quality_agent.execute = AsyncMock(return_value=[])

    ctx = ReviewContext(target_path=str(tmp_path))
    report = await pipeline.execute(str(tmp_path), context=ctx)

    # Static analysis findings must be preserved!
    assert report is not None
    assert len(report.issues) > 0
    assert any("Secret" in i.title for i in report.issues)
    assert ctx.status == ReviewOutcome.PARTIALLY_COMPLETED
    assert ctx.circuit_open is True


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_tasks_cleanly():
    async def long_running_task():
        await asyncio.sleep(10)

    task = asyncio.create_task(long_running_task())
    active_review_tasks.add(task)

    async with lifespan(app):
        pass

    # After lifespan shutdown exits, task must be cancelled
    assert task.cancelled() or task.done()
    active_review_tasks.clear()
