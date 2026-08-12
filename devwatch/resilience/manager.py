import time
import random
import asyncio
import logging
from typing import Dict, Optional, Callable, Any, Set, Type

from devwatch.config import Config
from devwatch.providers.base import LLMRequest, LLMResponse
from devwatch.resilience.circuit_breaker import CircuitBreaker
from devwatch.providers.exceptions import (
    ProviderError,
    CircuitBreakerOpenError,
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

logger = logging.getLogger("devwatch.resilience.manager")

NON_RETRYABLE_EXCEPTIONS: Set[Type[BaseException]] = {
    CircuitBreakerOpenError,
    ProviderQuotaExhaustedError,
    ProviderAuthenticationError,
    ProviderAuthorizationError,
    ProviderNonRetryableError,
    ProviderContextLengthError,
    ProviderContentPolicyError,
    ProviderConfigurationError,
    asyncio.CancelledError,
}



class ResilienceManager:
    """Centralized LLM Resilience Manager controlling concurrency, circuit breaking, token budgets, and backoff retries."""

    def __init__(self):
        self.semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_LLM_CALLS)
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.job_token_usage: Dict[str, int] = {}

    def get_circuit_breaker(self, provider_name: str) -> CircuitBreaker:
        if provider_name not in self.circuit_breakers:
            self.circuit_breakers[provider_name] = CircuitBreaker(provider_name=provider_name)
        return self.circuit_breakers[provider_name]

    def reset_job_token_usage(self, job_id: str) -> None:
        if job_id in self.job_token_usage:
            del self.job_token_usage[job_id]

    def track_token_usage(self, job_id: Optional[str], tokens: int) -> None:
        if not job_id:
            return
        current = self.job_token_usage.get(job_id, 0)
        new_total = current + tokens
        if new_total > Config.MAX_JOB_TOKEN_BUDGET:
            raise ProviderError(
                f"Job token budget exceeded ({new_total} tokens requested, max budget is {Config.MAX_JOB_TOKEN_BUDGET})."
            )
        self.job_token_usage[job_id] = new_total

    async def execute_with_resilience(
        self,
        func: Callable[..., Any],
        request: LLMRequest,
        job_id: Optional[str] = None,
        provider_name: str = "openrouter",
        max_retries: int = 3,
        base_backoff: float = 2.5,
        max_backoff: float = 15.0,
        jitter: float = 3.0,
    ) -> LLMResponse:
        """Execute LLM call with concurrency semaphores, circuit breaking, token budgeting, and bounded backoff."""
        cb = self.get_circuit_breaker(provider_name)

        for attempt in range(1, max_retries + 1):
            cb.allow_request()

            async with self.semaphore:
                try:
                    logger.debug(f"Resilience execution [Attempt {attempt}/{max_retries}] for model {request.model}")
                    
                    # Execute provider call with timeout
                    async with asyncio.timeout(Config.PROVIDER_CALL_TIMEOUT_SECONDS):
                        response: LLMResponse = await func(request)

                    # Verify response token budget
                    if response and response.usage:
                        self.track_token_usage(job_id, response.usage.total_tokens)

                    cb.record_success()
                    return response

                except tuple(NON_RETRYABLE_EXCEPTIONS) as err:
                    logger.error(f"Non-retryable provider exception [{type(err).__name__}]: {err}. Failing immediately with 0 retries.")
                    raise err

                except (ProviderRateLimitError, ProviderTimeoutError, ProviderTemporaryError, ProviderInvalidResponseError, TimeoutError, asyncio.TimeoutError) as err:
                    cb.record_failure()

                    if attempt >= max_retries:
                        logger.error(f"Resilience execution exhausted all {max_retries} retry attempts for {provider_name}.")
                        raise err

                    # Calculate backoff delay with exponential scaling and random jitter (2.5^attempt + jitter)
                    raw_delay = (base_backoff ** attempt) + random.uniform(1.0, max(1.0, jitter))
                    delay = min(max_backoff, raw_delay)

                    logger.warning(
                        f"Resilience retry [{attempt}/{max_retries}] on transient error ({type(err).__name__}). Backing off for {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)

        raise ProviderTemporaryError("Resilience execution failed after all retries exhausted.")


resilience_manager = ResilienceManager()
