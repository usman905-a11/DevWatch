import json
from typing import Annotated, Any, Dict, List

from typing_extensions import TypedDict

from devwatch.models import CodeIssue, IssueSeverity, ReviewReport
from devwatch.config import Config
from devwatch.review.models import ChangedRegion, ReviewTask, ToolEvidence


_SEVERITY_ORDER = {
    IssueSeverity.CRITICAL: 0,
    IssueSeverity.HIGH: 1,
    IssueSeverity.MEDIUM: 2,
    IssueSeverity.LOW: 3,
    IssueSeverity.INFO: 4,
}


def candidate_sort_key(issue: CodeIssue) -> tuple[int, str]:
    return (
        _SEVERITY_ORDER[issue.severity],
        json.dumps(issue.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
    )


def merge_candidates(left: List[CodeIssue], right: List[CodeIssue]) -> List[CodeIssue]:
    return sorted([*left, *right], key=candidate_sort_key)[: Config.MAX_CANDIDATE_FINDINGS]


def merge_failures(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted([*left, *right], key=lambda item: json.dumps(item, sort_keys=True))


class ReviewState(TypedDict, total=False):
    job_id: str
    target_path: str
    artifact_path: str
    artifact_files: List[str]
    artifact_hashes: Dict[str, str]
    changed_regions: List[ChangedRegion]
    tool_evidence: List[ToolEvidence]
    review_tasks: List[ReviewTask]
    candidate_findings: Annotated[List[CodeIssue], merge_candidates]
    failures: Annotated[List[Dict[str, Any]], merge_failures]
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
    candidate_findings: Annotated[List[CodeIssue], merge_candidates]
    failures: Annotated[List[Dict[str, Any]], merge_failures]
