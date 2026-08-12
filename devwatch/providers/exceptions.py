from typing import Optional


class ProviderError(Exception):
    """Base exception for all LLM provider errors."""

    def __init__(self, message: str, provider: Optional[str] = None, raw_error: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.raw_error = raw_error


class ProviderAuthenticationError(ProviderError):
    """Raised when provider authentication fails (invalid or missing API key)."""
    pass


class ProviderAuthorizationError(ProviderError):
    """Raised when client lacks permission for requested model or endpoint."""
    pass


class ProviderRateLimitError(ProviderError):
    """Raised when provider rate limit (RPM/TPM) is exceeded."""
    pass


class ProviderQuotaExhaustedError(ProviderRateLimitError):
    """Raised when provider account daily quota or credits are completely exhausted."""
    pass


class ProviderTimeoutError(ProviderError):
    """Raised when connection or read timeout occurs with LLM provider."""
    pass


class ProviderTemporaryError(ProviderError):
    """Raised when provider experiences temporary server errors (500, 502, 503, 504)."""
    pass


class CircuitBreakerOpenError(ProviderError):
    """Raised when circuit breaker is OPEN or HALF_OPEN probing, preventing calls to provider."""
    pass



class ProviderInvalidResponseError(ProviderError):
    """Raised when provider returns an empty or unparseable response."""
    pass


class ProviderContextLengthError(ProviderError):
    """Raised when input prompt exceeds model maximum context length."""
    pass


class ProviderContentPolicyError(ProviderError):
    """Raised when request or response violates provider content safety policy."""
    pass


class ProviderConfigurationError(ProviderError):
    """Raised when provider is misconfigured (missing environment variables or invalid URL)."""
    pass


class ProviderNonRetryableError(ProviderError):
    """Raised when provider returns unrecoverable client errors (400 Bad Request)."""
    pass
