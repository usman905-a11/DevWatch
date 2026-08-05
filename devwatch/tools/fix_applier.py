import os
from devwatch.patcher import RemediationPatcher
from devwatch.models import RemediationProposal, PatchValidationResult


def apply_code_fix(
    root_dir: str,
    file_path: str,
    line_number: int,
    target_snippet: str,
    replacement_code: str,
    finding_id: str = "legacy_finding",
    authorized_by: str = "user",
) -> PatchValidationResult:
    """Safely propose and apply atomic code remediation with validation, hash checks, and rollback support."""
    patcher = RemediationPatcher(root_dir)

    # 1. Propose fix & compute content hash
    proposal = patcher.propose_fix(
        file_path=file_path,
        finding_id=finding_id,
        start_line=line_number,
        end_line=line_number,
        target_snippet=target_snippet,
        replacement_code=replacement_code,
        reason="User requested code fix",
        author=authorized_by,
    )

    # 2. Apply proposal with explicit authorization
    result = patcher.apply_proposal(proposal, authorized_by=authorized_by)

    if not result.success:
        raise ValueError(result.error_message or "Failed to apply remediation patch")

    return result
