"""
ReviewOperations — a deep domain module orchestrating code review workflows.

Interface:
- audit_repository(target_path, client_identity, client_ip) -> ReviewReport
- audit_uploaded_files(files, client_identity, client_ip) -> ReviewReport
- audit_single_file(file_path, content, client_identity, client_ip) -> ReviewReport

Each operation encapsulates:
- Input validation
- Rate-limiting checks
- Pipeline execution
- Audit logging
- Error handling

This module is transport-agnostic: HTTP routers, CLI, and tests all use the same deep interface.
"""

from typing import List, Optional, Dict

from devwatch.config import Config
from devwatch.pipeline.dag import ReviewPipeline
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewReport
from devwatch.agents.llm import OpenRouterRateLimitError
from devwatch.rate_limiter import rate_limiter
from devwatch.audit_log import (
    log_review_created,
)
from devwatch.providers.exceptions import (
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
