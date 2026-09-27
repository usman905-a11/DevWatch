import operator
from typing import Annotated, Any, Dict, List

from typing_extensions import TypedDict

from devwatch.models import CodeIssue, ReviewReport
from devwatch.review.models import ChangedRegion, ReviewTask, ToolEvidence


class ReviewState(TypedDict, total=False):
    job_id: str
    target_path: str
    artifact_path: str
    artifact_files: List[str]
    artifact_hashes: Dict[str, str]
    changed_regions: List[ChangedRegion]
    tool_evidence: List[ToolEvidence]
    review_tasks: List[ReviewTask]
    candidate_findings: Annotated[List[CodeIssue], operator.add]
    failures: Annotated[List[Dict[str, Any]], operator.add]
    deduped_findings: List[CodeIssue]
    verified_findings: List[CodeIssue]
    confirmed_findings: List[CodeIssue]
    manual_review_candidates: List[CodeIssue]
    report: ReviewReport


class SpecialistState(TypedDict, total=False):
    task: ReviewTask
    artifact_path: str
    artifact_files: List[str]
    tool_evidence: List[ToolEvidence]
    candidate_findings: Annotated[List[CodeIssue], operator.add]
    failures: Annotated[List[Dict[str, Any]], operator.add]
