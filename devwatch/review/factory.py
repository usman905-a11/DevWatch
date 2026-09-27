from pathlib import Path

from devwatch.config import Config
from devwatch.providers.factory import get_provider
from devwatch.review.agents import RiskPlannerAgent, RoleReviewAgent, StrictVerifierAgent
from devwatch.review.engine import ReviewEngine
from devwatch.review.models import SpecialistRole


def create_review_engine() -> ReviewEngine:
    provider = get_provider()
    return ReviewEngine(
        planner=RiskPlannerAgent(provider=provider),
        specialists={
            role: RoleReviewAgent(role, provider=provider) for role in SpecialistRole
        },
        verifier=StrictVerifierAgent(provider=provider),
        verification_threshold=Config.VERIFICATION_CONFIDENCE_THRESHOLD,
        runs_dir=Path(Config.REVIEW_RUNS_DIR),
        run_commands=Config.REVIEW_COMMANDS_ENABLED,
        checkpoint_path=Path(Config.CHECKPOINT_DB_PATH),
    )
