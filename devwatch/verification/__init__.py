"""
Verification module — strategies for filtering and categorizing issues.
Centralizes verification decision-making logic.
"""

from devwatch.verification.strategy import (
    VerificationStrategy,
    DefaultVerificationStrategy,
    StrictVerificationStrategy,
    LenientVerificationStrategy,
)

__all__ = [
    "VerificationStrategy",
    "DefaultVerificationStrategy",
    "StrictVerificationStrategy",
    "LenientVerificationStrategy",
]
