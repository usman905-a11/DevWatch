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
