"""
VerificationStrategy — encapsulates issue filtering and categorization logic.

The verification workflow:
1. Receive candidate issues from security/quality agents
2. Apply verification strategy to filter false positives
3. Escalate uncertain high-severity findings for human review
4. Return filtered and categorized findings

This module is transport-agnostic and testable independently of the HTTP layer.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from devwatch.models import CodeIssue, IssueSeverity, VerificationStatus, VerificationItem

logger = logging.getLogger("devwatch.verification")


class VerificationStrategy(ABC):
    """
    Abstract base class for verification strategies.
    
    A verification strategy filters issues based on:
    - Verification status (ACCEPTED, REJECTED, UNCERTAIN, NEEDS_HUMAN_REVIEW)
    - Confidence scores
    - Severity levels
    """

    @abstractmethod
    def apply(
        self,
        issues: List[CodeIssue],
        verifications: Optional[List[VerificationItem]] = None,
    ) -> List[CodeIssue]:
        """
        Apply verification strategy to filter and categorize issues.
        
        Args:
            issues: Candidate issues from agents
            verifications: Optional verification decisions from LLM verifier
        
        Returns:
            Filtered list of issues with updated verification_status
        """
        pass


class DefaultVerificationStrategy(VerificationStrategy):
    """
    Default verification strategy: filters false positives and escalates uncertainty.
    
    Decision logic:
    - REJECTED or not is_true_positive → drop (false positive)
    - UNCERTAIN/NEEDS_HUMAN_REVIEW with confidence < 0.6 → escalate if CRITICAL/HIGH
    - Otherwise → accept and include
    """

    def apply(
        self,
        issues: List[CodeIssue],
        verifications: Optional[List[VerificationItem]] = None,
    ) -> List[CodeIssue]:
        """Apply default verification strategy to filter issues."""
        
        if not verifications:
            # No verification data; accept all issues as-is
            return issues

        # Build lookup maps: finding_id → verification, title → verification
        id_map = {}
        title_map = {}

        for item in verifications:
            if item.finding_id:
                id_map[item.finding_id.strip()] = item
            if item.issue_title:
                title_map[item.issue_title.lower().strip()] = item

        filtered_issues: List[CodeIssue] = []

        for issue in issues:
            # Look up verification by finding_id, fallback to title
            fid = issue.finding_id
            v_item = id_map.get(fid) if fid else None

            if not v_item and issue.title:
                v_item = title_map.get(issue.title.lower().strip())

            if not v_item:
                # No verification data for this issue; accept as-is
                filtered_issues.append(issue)
                continue

            status = v_item.status
            if isinstance(status, str):
                try:
                    status = VerificationStatus(status.upper())
                except ValueError:
                    status = (
                        VerificationStatus.ACCEPTED
                        if v_item.is_true_positive
                        else VerificationStatus.REJECTED
                    )

            issue.verification_rationale = v_item.reasoning

            # Decision Logic: Apply verification status to filter issues
            if status == VerificationStatus.REJECTED or not v_item.is_true_positive:
                logger.info(
                    f"Verification REJECTED false positive [{fid}]: '{issue.title}' in {issue.file_path}"
                )
                # Drop false positive
                continue

            if (
                status in (VerificationStatus.UNCERTAIN, VerificationStatus.NEEDS_HUMAN_REVIEW)
                or v_item.confidence < 0.6
            ):
                # Uncertain finding; escalate if high-severity
                if issue.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH):
                    logger.warning(
                        f"Escalating uncertain high-severity [{fid}] '{issue.title}' to NEEDS_HUMAN_REVIEW"
                    )
                    issue.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
                    filtered_issues.append(issue)
                else:
                    logger.info(
                        f"Dropping low-confidence non-critical [{fid}]: '{issue.title}'"
                    )
                    # Drop low-confidence non-critical
                    continue
            else:
                # Accepted finding
                issue.verification_status = VerificationStatus.ACCEPTED
                filtered_issues.append(issue)

        return filtered_issues


class StrictVerificationStrategy(VerificationStrategy):
    """
    Strict verification strategy: only accepts ACCEPTED findings.
    Drops everything else, including UNCERTAIN high-severity findings.
    
    Useful for production deployments where false negatives are preferred over false positives.
    """

    def apply(
        self,
        issues: List[CodeIssue],
        verifications: Optional[List[VerificationItem]] = None,
    ) -> List[CodeIssue]:
        """Apply strict verification: only ACCEPTED findings pass."""
        
        if not verifications:
            return issues

        id_map = {}
        title_map = {}

        for item in verifications:
            if item.finding_id:
                id_map[item.finding_id.strip()] = item
            if item.issue_title:
                title_map[item.issue_title.lower().strip()] = item

        filtered_issues: List[CodeIssue] = []

        for issue in issues:
            fid = issue.finding_id
            v_item = id_map.get(fid) if fid else None

            if not v_item and issue.title:
                v_item = title_map.get(issue.title.lower().strip())

            if not v_item or not v_item.is_true_positive:
                # No verification or not a true positive; drop
                continue

            status = v_item.status
            if isinstance(status, str):
                try:
                    status = VerificationStatus(status.upper())
                except ValueError:
                    status = VerificationStatus.REJECTED

            # Only accept ACCEPTED findings
            if status == VerificationStatus.ACCEPTED and v_item.confidence >= 0.8:
                issue.verification_status = VerificationStatus.ACCEPTED
                issue.verification_rationale = v_item.reasoning
                filtered_issues.append(issue)
            else:
                logger.debug(
                    f"Strict verification dropped [{fid}]: status={status}, confidence={v_item.confidence}"
                )

        return filtered_issues


class LenientVerificationStrategy(VerificationStrategy):
    """
    Lenient verification strategy: accepts both ACCEPTED and UNCERTAIN findings.
    Escalates high-severity, but includes all others.
    
    Useful for development/testing where false positives are acceptable for better coverage.
    """

    def apply(
        self,
        issues: List[CodeIssue],
        verifications: Optional[List[VerificationItem]] = None,
    ) -> List[CodeIssue]:
        """Apply lenient verification: accept most findings."""
        
        if not verifications:
            return issues

        id_map = {}
        title_map = {}

        for item in verifications:
            if item.finding_id:
                id_map[item.finding_id.strip()] = item
            if item.issue_title:
                title_map[item.issue_title.lower().strip()] = item

        filtered_issues: List[CodeIssue] = []

        for issue in issues:
            fid = issue.finding_id
            v_item = id_map.get(fid) if fid else None

            if not v_item and issue.title:
                v_item = title_map.get(issue.title.lower().strip())

            if not v_item:
                # No verification; accept as-is
                filtered_issues.append(issue)
                continue

            status = v_item.status
            if isinstance(status, str):
                try:
                    status = VerificationStatus(status.upper())
                except ValueError:
                    status = VerificationStatus.ACCEPTED

            issue.verification_rationale = v_item.reasoning

            # Drop only explicit rejects
            if status == VerificationStatus.REJECTED or not v_item.is_true_positive:
                logger.info(
                    f"Lenient verification dropped explicit reject [{fid}]: '{issue.title}'"
                )
                continue

            # Accept everything else
            if status == VerificationStatus.UNCERTAIN or v_item.confidence < 0.6:
                if issue.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH):
                    issue.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
                else:
                    issue.verification_status = VerificationStatus.UNCERTAIN
            else:
                issue.verification_status = VerificationStatus.ACCEPTED

            filtered_issues.append(issue)

        return filtered_issues
