import re
import hashlib
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator



class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class VerificationStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


def generate_evidence_fingerprint(code_snippet: Optional[str]) -> str:
    """Generate SHA-256 fingerprint from normalized code snippet."""
    if not code_snippet:
        return "empty_fingerprint"
    # Remove line numbers added by add_line_numbers (e.g. "   1 | ")
    cleaned = re.sub(r"^\s*\d+\s*\|\s*", "", code_snippet, flags=re.MULTILINE)
    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def generate_finding_id(
    file_path: str,
    rule_id: Optional[str],
    fingerprint: str,
    symbol_name: Optional[str] = None,
) -> str:
    """Generate stable SHA-256 finding ID based on normalized path, rule ID, fingerprint, and symbol name."""
    norm_path = file_path.replace("\\", "/").strip("./")
    rid = (rule_id or "generic_rule").lower()
    sym = (symbol_name or "").lower()
    key = f"{norm_path}:{rid}:{fingerprint}:{sym}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class CodeIssue(BaseModel):
    finding_id: Optional[str] = None
    file_path: str
    line_number: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    severity: IssueSeverity
    category: str
    rule_id: Optional[str] = None
    title: str
    description: str
    suggestion: str
    code_snippet: Optional[str] = None
    replacement_code: Optional[str] = None
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    cwe_id: Optional[str] = None
    owasp_category: Optional[str] = None
    symbol_name: Optional[str] = None
    evidence_fingerprint: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.ACCEPTED
    verification_rationale: Optional[str] = None
    source_type: str = "agent"
    agent_id: Optional[str] = None
    agent_version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.ensure_identity()

    def ensure_identity(self) -> str:
        if not self.start_line and self.line_number:
            self.start_line = self.line_number
        if not self.end_line and self.line_number:
            self.end_line = self.line_number

        if not self.rule_id:
            self.rule_id = self.cwe_id or self.category.lower().replace(" ", "_")

        if not self.evidence_fingerprint:
            self.evidence_fingerprint = generate_evidence_fingerprint(self.code_snippet or self.title)

        if not self.finding_id:
            self.finding_id = generate_finding_id(
                file_path=self.file_path,
                rule_id=self.rule_id,
                fingerprint=self.evidence_fingerprint,
                symbol_name=self.symbol_name,
            )
        return self.finding_id

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v: Any) -> IssueSeverity:
        if isinstance(v, str):
            val = v.upper().strip()
            try:
                return IssueSeverity(val)
            except ValueError:
                return IssueSeverity.MEDIUM
        return v



# Alias for canonical domain model
CanonicalFinding = CodeIssue


class StructuredCodeIssue(BaseModel):

    line_number: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    severity: IssueSeverity = IssueSeverity.MEDIUM
    category: str = "Code Review"
    rule_id: Optional[str] = None
    title: str
    description: str
    suggestion: str
    code_snippet: Optional[str] = None
    replacement_code: Optional[str] = None
    confidence_score: float = Field(default=0.9, ge=0.0, le=1.0)
    cwe_id: Optional[str] = None
    symbol_name: Optional[str] = None

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v: Any) -> IssueSeverity:
        if isinstance(v, str):
            val = v.upper().strip()
            try:
                return IssueSeverity(val)
            except ValueError:
                return IssueSeverity.MEDIUM
        return v



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
    finding_id: Optional[str] = Field(default=None, description="Stable SHA-256 finding_id being verified")
    issue_title: Optional[str] = Field(default=None, description="Title of finding being verified (legacy fallback)")
    status: VerificationStatus = Field(default=VerificationStatus.ACCEPTED, description="ACCEPTED, REJECTED, UNCERTAIN, or NEEDS_HUMAN_REVIEW")
    is_true_positive: bool = Field(default=True, description="True if accepted, False if rejected")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    reasoning: str = Field(default="", description="Explanation of verification decision")


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


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class RemediationProposal(BaseModel):
    proposal_id: str
    finding_id: str
    file_path: str
    expected_content_hash: str
    start_line: int
    end_line: int
    target_snippet: str
    replacement_code: str
    reason: str
    author: str = "agent"
    authorized_by: Optional[str] = None
    created_at: float = Field(default_factory=lambda: 1700000000.0)
    status: ProposalStatus = ProposalStatus.PROPOSED
    diff_preview: Optional[str] = None


class PatchValidationResult(BaseModel):
    success: bool
    proposal_id: str
    diff_preview: str = ""
    error_message: Optional[str] = None
    backup_created: bool = False
    rolled_back: bool = False

    def __bool__(self) -> bool:
        return self.success

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, bool):
            return self.success == other
        return super().__eq__(other)


    def __bool__(self) -> bool:
        return self.success


