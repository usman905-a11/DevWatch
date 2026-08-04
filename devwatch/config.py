import os
from enum import Enum


class ModelTier(Enum):
    FAST = "FAST"
    HEAVY = "HEAVY"


class Config:
    @classmethod
    def get_default_model(cls, is_heavy: bool = False) -> str:
        if os.getenv("OPENROUTER_API_KEY"):
            return "openrouter/free"
        return "gpt-4o" if is_heavy else "gpt-4o-mini"

    @classmethod
    def get_model_for_tier(cls, tier: ModelTier) -> str:
        if tier == ModelTier.FAST:
            return os.getenv("DEVWATCH_FAST_MODEL", cls.get_default_model(is_heavy=False))
        return os.getenv("DEVWATCH_HEAVY_MODEL", cls.get_default_model(is_heavy=True))

