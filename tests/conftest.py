import pytest
from devwatch.resilience.manager import resilience_manager
from devwatch.providers.factory import set_provider, reset_provider
from devwatch.providers.fake_provider import FakeLLMProvider


@pytest.fixture(autouse=True)
def reset_resilience_circuit_breakers():
    """Keep the test suite deterministic and prevent accidental live provider calls."""
    resilience_manager.circuit_breakers.clear()
    set_provider(FakeLLMProvider())

    yield

    resilience_manager.circuit_breakers.clear()
    reset_provider()
