from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from devwatch.models import CodeIssue, VerificationStatus
from devwatch.models import StructuredCodeIssue


class SpecialistRole(str, Enum):
    SECURITY = "security"
    ARCHITECTURE_API = "architecture_api"
    CORRECTNESS = "correctness"
    PERFORMANCE = "performance_concurrency"


class ChangedRegion(BaseModel):
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> "ChangedRegion":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class ToolEvidence(BaseModel):
    source: str
    summary: str
    command: List[str] = Field(default_factory=list)
    exit_code: Optional[int] = None
    duration_ms: float = Field(default=0.0, ge=0.0)
    stdout: str = ""
    stderr: str = ""
    conclusive: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RepositorySnapshot(BaseModel):
    root_path: str
    artifact_path: str
    content_hash: str
    files: List[str] = Field(default_factory=list)
    content_hashes: Dict[str, str] = Field(default_factory=dict)
    line_counts: Dict[str, int] = Field(default_factory=dict)


class CommandSpec(BaseModel):
    name: str
    argv: List[str] = Field(min_length=1)
    cwd: str = "."


class ReviewTask(BaseModel):
    task_id: str
    specialist: SpecialistRole
    files: List[str] = Field(min_length=1)
    focus: str
    changed_regions: List[ChangedRegion] = Field(default_factory=list)
    context_files: List[str] = Field(default_factory=list)
    evidence: List[ToolEvidence] = Field(default_factory=list)


class VerificationDecision(BaseModel):
    finding_id: str
    status: VerificationStatus
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class ReviewMetrics(BaseModel):
    files_changed: int = 0
    files_reviewed: int = 0
    specialist_tasks: int = 0
    candidate_findings: int = 0
    confirmed_findings: int = 0
    suppressed_findings: int = 0
    llm_calls: int = 0
    tool_runs: int = 0


class PlannedTask(BaseModel):
    specialist: SpecialistRole
    files: List[str] = Field(min_length=1)
    focus: str


class StructuredReviewPlan(BaseModel):
    tasks: List[PlannedTask] = Field(default_factory=list)


class StructuredSpecialistIssue(StructuredCodeIssue):
    file_path: str


class StructuredSpecialistResponse(BaseModel):
    issues: List[StructuredSpecialistIssue] = Field(default_factory=list)


CandidateFinding = CodeIssue
