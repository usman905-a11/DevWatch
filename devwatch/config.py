import os
from enum import Enum


class ModelTier(Enum):
    FAST = "FAST"
    HEAVY = "HEAVY"


class Config:
    FAST_MODEL: str = os.getenv("DEVWATCH_FAST_MODEL", "gpt-4o-mini")
    HEAVY_MODEL: str = os.getenv("DEVWATCH_HEAVY_MODEL", "gpt-4o")

    @classmethod
    def get_model_for_tier(cls, tier: ModelTier) -> str:
        if tier == ModelTier.FAST:
            return os.getenv("DEVWATCH_FAST_MODEL", cls.FAST_MODEL)
        return os.getenv("DEVWATCH_HEAVY_MODEL", cls.HEAVY_MODEL)
