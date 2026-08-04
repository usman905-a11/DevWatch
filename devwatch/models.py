from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class CodeIssue(BaseModel):
    file_path: str
    line_number: Optional[int] = None
    severity: IssueSeverity
    category: str
    title: str
    description: str
    suggestion: str
    code_snippet: Optional[str] = None
    replacement_code: Optional[str] = None
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    cwe_id: Optional[str] = None


class StructuredCodeIssue(BaseModel):
    line_number: Optional[int] = None
    severity: IssueSeverity = IssueSeverity.MEDIUM
    category: str = "Code Review"
    title: str
    description: str
    suggestion: str
    code_snippet: Optional[str] = None
    replacement_code: Optional[str] = None
    confidence_score: float = Field(default=0.9, ge=0.0, le=1.0)
    cwe_id: Optional[str] = None


class StructuredSecurityResponse(BaseModel):
    issues: List[StructuredCodeIssue] = Field(default_factory=list)


class StructuredQualityResponse(BaseModel):
    issues: List[StructuredCodeIssue] = Field(default_factory=list)


class StructuredPlannerResponse(BaseModel):
    priority_files: List[str] = Field(default_factory=list)
    focus_areas: List[str] = Field(default_factory=list)


class StructuredSynthesizerResponse(BaseModel):
    verdict: str = Field(default="Deploy with conditions", description="Overall Verdict: 'BLOCK deployment', 'Deploy with conditions', or 'Safe to deploy'")
    top_threat: str = Field(default="", description="Single most dangerous finding by impact and exploitability with file:line reference")
    summary_bullets: List[str] = Field(default_factory=list, description="3-5 executive summary points")
    executive_summary: str = Field(default="", description="Full executive summary in markdown")


class VerificationItem(BaseModel):
    issue_title: str
    is_true_positive: bool = Field(default=True, description="True if the issue is a genuine defect, False if false positive/hallucination")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    reasoning: str = Field(default="", description="1-sentence explanation of verification decision")


class StructuredVerificationResponse(BaseModel):
    verifications: List[VerificationItem] = Field(default_factory=list)


class ReviewScope(BaseModel):
    target_path: str
    files_to_review: List[str] = Field(default_factory=list)
    focus_areas: List[str] = Field(default_factory=list)


class ReviewReport(BaseModel):
    target_path: str
    issues: List[CodeIssue] = Field(default_factory=list)
    summary: str = ""

    @property
    def total_issues(self) -> int:
        return len(self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.LOW)


class AgentStepUpdate(BaseModel):
    agent_name: str
    status: str  # e.g., "IDLE", "RUNNING", "COMPLETED", "FAILED"
    message: str
    timestamp: Optional[float] = None
