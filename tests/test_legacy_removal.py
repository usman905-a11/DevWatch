"""The shipped package contains one runtime, canonical prompts/configuration only."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBSOLETE = ["agents", "pipeline", "routers", "operations", "prompts", "verification", "tools", "resilience",
    "models.py", "server.py", "scanner.py", "storage.py", "reports.py", "auth.py", "audit_log.py", "rate_limiter.py",
    "cache.py", "chunker.py", "review/engine.py", "review/models.py", "review/agents.py", "review/state.py",
    "review/factory.py", "review/evidence.py", "review/runner.py", "review/reporting.py", "providers/factory.py", "providers/fake_provider.py"]


def test_obsolete_runtime_and_compatibility_modules_are_removed():
    assert [path for path in OBSOLETE if (ROOT / "devwatch" / path).exists()] == []


def test_public_review_contracts_and_config_have_no_old_tiers_or_budget_aliases():
    import devwatch.review as review
    from devwatch.review.contracts import AgentId, ReviewTask
    assert review.AgentId is AgentId and review.ReviewTask is ReviewTask
    source = (ROOT / "devwatch/config.py").read_text()
    for obsolete in ("FAST_MODEL", "HEAVY_MODEL", "MAX_TOKENS_PER_JOB", "GLOBAL_REVIEW_TIMEOUT", "REVIEW_COMMANDS_ENABLED"):
        assert obsolete not in source
