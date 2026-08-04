import asyncio
import uuid
from enum import Enum

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from devwatch.models import CodeIssue, ReviewScope, ReviewReport


class ReviewOutcome(str, Enum):
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class ReviewContext(BaseModel):
    """Typed execution context tracking pipeline state, findings, metrics, and failures."""

    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:8]}")
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:12]}")
    workspace_id: str = "default_workspace"
    owner_id: str = "default_user"
    target_path: str = "."
    
    scope: Optional[ReviewScope] = None
    selected_files: List[str] = Field(default_factory=list)
    cancellation_requested: bool = False
    
    static_findings: List[CodeIssue] = Field(default_factory=list)
    security_findings: List[CodeIssue] = Field(default_factory=list)
    quality_findings: List[CodeIssue] = Field(default_factory=list)
    verified_findings: List[CodeIssue] = Field(default_factory=list)
    final_issues: List[CodeIssue] = Field(default_factory=list)
    
    stage_failures: List[Dict[str, Any]] = Field(default_factory=list)
    status: ReviewOutcome = ReviewOutcome.COMPLETED
    metrics: Dict[str, Any] = Field(default_factory=dict)

    def check_cancellation(self) -> None:
        """Check if cancellation was requested and raise CancelledError if True."""
        if self.cancellation_requested:
            self.status = ReviewOutcome.CANCELLED
            raise asyncio.CancelledError("Review execution cancelled by user")

    def record_failure(self, stage: str, agent_or_component: str, error: Exception, details: Optional[Dict[str, Any]] = None) -> None:
        """Record a partial failure without crashing the whole pipeline."""
        self.stage_failures.append({
            "stage": stage,
            "component": agent_or_component,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "details": details or {},
        })
        if self.status == ReviewOutcome.COMPLETED:
            self.status = ReviewOutcome.PARTIALLY_COMPLETED
