import time
import logging
from enum import Enum
from devwatch.config import Config
from devwatch.providers.exceptions import ProviderTemporaryError

logger = logging.getLogger("devwatch.resilience.circuit_breaker")


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """3-State Circuit Breaker preventing cascade failures during LLM provider outages."""

    def __init__(
        self,
        provider_name: str = "default",
        failure_threshold: int = Config.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout: float = Config.CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
    ):
        self.provider_name = provider_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = time.time()
        self.half_open_probe_in_flight = False

    def allow_request(self) -> bool:

        now = time.time()

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if now - self.last_state_change >= self.recovery_timeout:
                logger.info(f"CircuitBreaker [{self.provider_name}] OPEN timeout expired -> transitioning to HALF_OPEN probe state")
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now
                self.half_open_probe_in_flight = True
                return True
            else:
                remaining = int(self.recovery_timeout - (now - self.last_state_change))
                raise ProviderTemporaryError(
                    f"Circuit breaker for provider '{self.provider_name}' is OPEN due to repeated failures. "
                    f"Probe recovery in {remaining}s.",
                    provider=self.provider_name,
                )

        if self.state == CircuitState.HALF_OPEN:
            if not self.half_open_probe_in_flight:
                self.half_open_probe_in_flight = True
                return True
            raise ProviderTemporaryError(
                f"Circuit breaker for provider '{self.provider_name}' is HALF_OPEN and testing probe request.",
                provider=self.provider_name,
            )

        return True

    def record_success(self) -> None:
        if self.state != CircuitState.CLOSED:
            logger.info(f"CircuitBreaker [{self.provider_name}] Probe succeeded -> transitioning to CLOSED")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_probe_in_flight = False
        self.last_state_change = time.time()

    def record_failure(self) -> None:
        self.failure_count += 1
        self.half_open_probe_in_flight = False
        if self.failure_count >= self.failure_threshold or self.state == CircuitState.HALF_OPEN:
            if self.state != CircuitState.OPEN:
                logger.warning(
                    f"CircuitBreaker [{self.provider_name}] Failure threshold ({self.failure_count}/{self.failure_threshold}) reached -> TRIPPING TO OPEN"
                )
            self.state = CircuitState.OPEN
            self.last_state_change = time.time()
