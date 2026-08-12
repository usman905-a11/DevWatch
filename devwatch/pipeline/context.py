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
    circuit_open: bool = False

    static_findings: List[CodeIssue] = Field(default_factory=list)

    security_findings: List[CodeIssue] = Field(default_factory=list)
    quality_findings: List[CodeIssue] = Field(default_factory=list)
    verified_findings: List[CodeIssue] = Field(default_factory=list)
    final_issues: List[CodeIssue] = Field(default_factory=list)
    
    stage_failures: List[Dict[str, Any]] = Field(default_factory=list)
    status: ReviewOutcome = ReviewOutcome.COMPLETED
    metrics: Dict[str, Any] = Field(default_factory=dict)

    # Scalability & Cost Telemetry (Phase 11)
    tokens_by_agent: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    skipped_files: List[str] = Field(default_factory=list)
    chunked_inputs: List[Dict[str, Any]] = Field(default_factory=list)
    cache_hits: int = 0

    def record_tokens(self, agent_id: str, prompt_tokens: int, completion_tokens: int, estimated_cost: float = 0.0) -> None:
        if agent_id not in self.tokens_by_agent:
            self.tokens_by_agent[agent_id] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.tokens_by_agent[agent_id]["prompt_tokens"] += prompt_tokens
        self.tokens_by_agent[agent_id]["completion_tokens"] += completion_tokens
        self.tokens_by_agent[agent_id]["total_tokens"] += (prompt_tokens + completion_tokens)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.estimated_cost_usd += estimated_cost


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
