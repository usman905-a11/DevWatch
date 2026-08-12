"""
ReviewOperations — a deep domain module orchestrating code review workflows.

Interface:
- audit_repository(target_path, client_identity, client_ip) -> ReviewReport
- audit_uploaded_files(files, client_identity, client_ip) -> ReviewReport
- audit_single_file(file_path, content, client_identity, client_ip) -> ReviewReport
- apply_quick_fix(root_path, file_path, finding_id, replacement_code, client_identity, client_ip) -> Dict
- propose_remediation_fix(...) -> RemediationProposal

Each operation encapsulates:
- Input validation
- Rate-limiting checks
- Pipeline execution
- Audit logging
- Error handling

This module is transport-agnostic: HTTP routers, CLI, and tests all use the same deep interface.
"""

import time
from typing import List, Optional, Dict, Any

from devwatch.config import Config
from devwatch.pipeline.dag import ReviewPipeline
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewReport, RemediationProposal, CodeIssue
from devwatch.agents.llm import OpenRouterRateLimitError
from devwatch.auth import verify_api_key
from devwatch.rate_limiter import rate_limiter
from devwatch.audit_log import (
    log_review_created,
    log_fix_applied,
    log_proposal_created,
    log_remediation_event,
)
from devwatch.patcher import RemediationPatcher
from devwatch.providers.exceptions import (
    ProviderError,
    ProviderRateLimitError,
    ProviderQuotaExhaustedError,
)


class ReviewOperations:
    """
    High-level review operations with validation, rate-limiting, and audit logging built-in.
    
    Design principle: Each operation method is a complete, self-contained workflow.
    Callers need only provide domain inputs (path, client identity, client IP);
    validation, rate-limiting, and audit logging are automatic.
    """

    def __init__(self):
        self.pipeline = ReviewPipeline()
        self.patcher = None  # Lazily initialized per operation with root_path

    async def audit_repository(
        self,
        target_path: str,
        client_identity: str,
        client_ip: str,
        step_callback: Optional[callable] = None,
    ) -> ReviewReport:
        """
        Audit a local repository (directory scan + full review pipeline).
        
        Workflow:
        1. Validate target_path (directory exists, within sandbox)
        2. Check rate limit
        3. Execute pipeline
        4. Audit log the operation
        5. Return report
        
        Raises:
            ValueError: if target_path is invalid or blocked
            HTTPException(429): if rate limit exceeded
            HTTPException(500): if pipeline fails
        """
        # Step 1: Validate (will raise if invalid)
        scanner = CodebaseScanner(target_path)

        # Step 2: Rate-limit check
        rate_limiter.check_rate_limit(
            client_ip,
            Config.RATE_LIMIT_REVIEWS_RPM,
            window_seconds=60,
            endpoint="/api/review",
        )

        # Step 3: Execute pipeline
        try:
            pipeline = ReviewPipeline(step_callback=step_callback)
            report = await pipeline.execute(target_path)
        except OpenRouterRateLimitError as e:
            raise Exception(f"OpenRouter rate limit: {str(e)}")
        except ProviderQuotaExhaustedError as e:
            raise Exception(
                "LLM provider quota exhausted. Please try again later or use a different API key."
            )
        except ProviderRateLimitError as e:
            raise Exception(
                "LLM provider rate limit exceeded. Please wait and retry."
            )
        except Exception as e:
            if "429" in str(e) or "Rate limit" in str(e):
                raise Exception(
                    "LLM provider rate limit exceeded. Please wait and retry."
                )
            raise

        # Step 4: Audit log
        log_review_created("repository", target_path, client_identity)

        # Step 5: Return
        return report

    async def audit_uploaded_files(
        self,
        files: List[Dict[str, str]],
        client_identity: str,
        client_ip: str,
    ) -> ReviewReport:
        """
        Audit uploaded files (in-memory batch review).
        
        Input: list of {'file_path': str, 'content': str} dicts
        
        Workflow:
        1. Check rate limit
        2. Execute pipeline on file batch
        3. Audit log
        4. Return report
        """
        # Step 1: Rate-limit check
        rate_limiter.check_rate_limit(
            client_ip,
            Config.RATE_LIMIT_REVIEWS_RPM,
            window_seconds=60,
            endpoint="/api/review/files",
        )

        # Step 2: Execute pipeline
        try:
            pipeline = ReviewPipeline()
            report = await pipeline.arun_files_audit(files)
        except OpenRouterRateLimitError as e:
            raise Exception(f"OpenRouter rate limit: {str(e)}")
        except Exception as e:
            if "429" in str(e) or "Rate limit" in str(e):
                raise Exception(
                    "LLM provider rate limit exceeded. Please wait and retry."
                )
            raise

        # Step 3: Audit log
        log_review_created("in_memory_batch", "uploaded_files", client_identity)

        # Step 4: Return
        return report

    async def audit_single_file(
        self,
        file_path: str,
        content: str,
        client_identity: str,
        client_ip: str,
    ) -> ReviewReport:
        """
        Audit a single file (in-memory review).
        
        Workflow:
        1. Check rate limit
        2. Execute pipeline on single file
        3. Audit log
        4. Return report
        """
        # Step 1: Rate-limit check
        rate_limiter.check_rate_limit(
            client_ip,
            Config.RATE_LIMIT_REVIEWS_RPM,
            window_seconds=60,
            endpoint="/api/review/file",
        )

        # Step 2: Execute pipeline
        try:
            pipeline = ReviewPipeline()
            report = await pipeline.arun_file_audit(file_path, content)
        except OpenRouterRateLimitError as e:
            raise Exception(f"OpenRouter rate limit: {str(e)}")
        except Exception as e:
            if "429" in str(e) or "Rate limit" in str(e):
                raise Exception(
                    "LLM provider rate limit exceeded. Please wait and retry."
                )
            raise

        # Step 3: Audit log
        log_review_created("single_file", file_path, client_identity)

        # Step 4: Return
        return report

    async def apply_quick_fix(
        self,
        root_path: str,
        file_path: str,
        finding_id: str,
        target_snippet: str,
        replacement_code: str,
        line_number: int,
        client_identity: str,
        client_ip: str,
    ) -> Dict[str, Any]:
        """
        Apply a quick fix to a file (no approval step).
        
        Workflow:
        1. Validate root_path
        2. Check rate limit
        3. Propose fix
        4. Apply proposal
        5. Audit log
        6. Return result
        """
        # Step 1: Validate
        patcher = RemediationPatcher(root_path)

        # Step 2: Rate-limit check
        rate_limiter.check_rate_limit(
            client_ip,
            Config.RATE_LIMIT_RPM,
            window_seconds=60,
            endpoint="/api/review/apply-fix",
        )

        # Step 3 & 4: Propose and apply
        try:
            proposal = patcher.propose_fix(
                file_path=file_path,
                finding_id=finding_id,
                start_line=line_number,
                end_line=line_number,
                target_snippet=target_snippet,
                replacement_code=replacement_code,
                reason="Quick fix application",
                author=client_identity,
            )
            result = patcher.apply_proposal(proposal, authorized_by=client_identity)

            if not result.success:
                raise Exception(f"Fix application failed: {result.error_message}")

            # Step 5: Audit log
            log_fix_applied(file_path, line_number, client_identity)

            # Step 6: Return
            return {
                "status": "success",
                "file_path": file_path,
                "line_number": line_number,
                "modified": result.success,
                "diff_preview": result.diff_preview,
            }
        except Exception as e:
            raise

    def propose_remediation_fix(
        self,
        root_path: str,
        file_path: str,
        finding_id: str,
        start_line: int,
        end_line: int,
        target_snippet: str,
        replacement_code: str,
        reason: str,
        client_identity: str,
        client_ip: str,
    ) -> RemediationProposal:
        """
        Propose a remediation fix (creates a proposal object; does not apply).
        
        Workflow:
        1. Validate root_path
        2. Check rate limit
        3. Create proposal
        4. Audit log
        5. Return proposal
        """
        # Step 1: Validate
        patcher = RemediationPatcher(root_path)

        # Step 2: Rate-limit check
        rate_limiter.check_rate_limit(
            client_ip,
            Config.RATE_LIMIT_RPM,
            window_seconds=60,
            endpoint="/api/review/propose-fix",
        )

        # Step 3: Create proposal
        proposal = patcher.propose_fix(
            file_path=file_path,
            finding_id=finding_id,
            start_line=start_line,
            end_line=end_line,
            target_snippet=target_snippet,
            replacement_code=replacement_code,
            reason=reason,
            author=client_identity,
        )

        # Step 4: Audit log
        log_proposal_created(proposal.proposal_id, finding_id, file_path, client_identity)

        # Step 5: Return
        return proposal

    def apply_remediation_proposal(
        self,
        root_path: str,
        proposal: RemediationProposal,
        client_identity: str,
        client_ip: str,
    ) -> Dict[str, Any]:
        """
        Apply a previously-proposed remediation fix.
        
        Workflow:
        1. Validate root_path
        2. Check rate limit
        3. Apply proposal
        4. Audit log
        5. Return result
        """
        # Step 1: Validate
        patcher = RemediationPatcher(root_path)

        # Step 2: Rate-limit check
        rate_limiter.check_rate_limit(
            client_ip,
            Config.RATE_LIMIT_RPM,
            window_seconds=60,
            endpoint="/api/review/apply-proposal",
        )

        # Step 3: Apply
        result = patcher.apply_proposal(proposal, authorized_by=client_identity)

        if not result.success:
            raise Exception(f"Proposal application failed: {result.error_message}")

        # Step 4: Audit log
        log_remediation_event(
            "REMEDIATION_APPLIED",
            proposal.proposal_id,
            proposal.file_path,
            client_identity,
        )

        # Step 5: Return
        return {"status": "success", "result": result.model_dump()}
