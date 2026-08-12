import os
import pytest
from devwatch.resilience.manager import resilience_manager
from devwatch.providers.factory import set_provider, reset_provider
from devwatch.providers.fake_provider import FakeLLMProvider


@pytest.fixture(autouse=True)
def reset_resilience_circuit_breakers():
    """Ensure circuit breakers start in a clean state and fallback to FakeLLMProvider if offline."""
    resilience_manager.circuit_breakers.clear()

    has_api_key = any(
        os.getenv(k)
        and not os.getenv(k).startswith("mock")
        and not os.getenv(k).startswith("sk-or-v1-mock")
        and not os.getenv(k).startswith("your_")
        and not os.getenv(k).startswith("your-")
        for k in ["GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"]
    )
    if not has_api_key:
        set_provider(FakeLLMProvider())

    yield

    resilience_manager.circuit_breakers.clear()
    reset_provider()
