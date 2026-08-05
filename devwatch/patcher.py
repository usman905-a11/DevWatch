import os
import ast
import uuid
import time
import shutil
import hashlib
import difflib
import logging
from pathlib import Path
from typing import Optional, List, Tuple

from devwatch.scanner import CodebaseScanner
from devwatch.models import RemediationProposal, PatchValidationResult, ProposalStatus
from devwatch.audit_log import _log_event
from devwatch.tools.static_analyzer import ASTStaticAnalyzerTool

logger = logging.getLogger("devwatch.patcher")


class RemediationPatcher:
    """Proposal-based safe patching engine with atomic backups, content hash checks, syntax validation, and automatic rollback."""

    def __init__(self, root_dir: str = "."):
        self.root_dir = root_dir
        self.scanner = CodebaseScanner(root_dir)
        self.ast_tool = ASTStaticAnalyzerTool()

    def propose_fix(
        self,
        file_path: str,
        finding_id: str,
        start_line: int,
        end_line: int,
        target_snippet: str,
        replacement_code: str,
        reason: str,
        author: str = "agent",
    ) -> RemediationProposal:
        """Create a safe RemediationProposal with unified diff preview without modifying source file."""
        safe_path = self.scanner._resolve_safe_path(file_path)
        if not safe_path.exists() or safe_path.is_dir():
            raise FileNotFoundError(f"File not found: '{file_path}'")

        raw_bytes = safe_path.read_bytes()
        expected_hash = hashlib.sha256(raw_bytes).hexdigest()

        content = raw_bytes.decode("utf-8", errors="replace")
        lines = content.splitlines(keepends=True)

        diff = self._generate_diff(file_path, lines, start_line, end_line, target_snippet, replacement_code)

        proposal_id = str(uuid.uuid4())[:8]
        return RemediationProposal(
            proposal_id=proposal_id,
            finding_id=finding_id,
            file_path=file_path.replace("\\", "/"),
            expected_content_hash=expected_hash,
            start_line=start_line,
            end_line=end_line,
            target_snippet=target_snippet,
            replacement_code=replacement_code,
            reason=reason,
            author=author,
            created_at=time.time(),
            status=ProposalStatus.PROPOSED,
            diff_preview=diff,
        )

    def apply_proposal(self, proposal: RemediationProposal, authorized_by: str) -> PatchValidationResult:
        """Validate, apply atomically, verify syntax & static checks, and roll back on failure."""
        proposal_id = proposal.proposal_id
        file_path = proposal.file_path

        # 1. Authorization check
        if not authorized_by or not authorized_by.strip():
            _log_event("REMEDIATION_FAILED", "HIGH", {"proposal_id": proposal_id, "reason": "Unauthorized proposal execution"})
            return PatchValidationResult(
                success=False,
                proposal_id=proposal_id,
                error_message="Unauthorized: Explicit user authorization required to apply patches.",
            )

        proposal.authorized_by = authorized_by

        # 2. Path Sandbox Validation
        try:
            safe_path = self.scanner._resolve_safe_path(file_path)
        except ValueError as err:
            _log_event("REMEDIATION_FAILED", "HIGH", {"proposal_id": proposal_id, "file_path": file_path, "reason": str(err)})
            return PatchValidationResult(
                success=False,
                proposal_id=proposal_id,
                error_message=f"Path traversal or invalid path: {str(err)}",
            )

        if not safe_path.exists() or safe_path.is_dir():
            return PatchValidationResult(
                success=False,
                proposal_id=proposal_id,
                error_message=f"File not found: '{file_path}'",
            )

        # 3. Content Hash Check (Stale Source Validation)
        current_bytes = safe_path.read_bytes()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        if current_hash != proposal.expected_content_hash:
            _log_event("REMEDIATION_FAILED", "WARNING", {"proposal_id": proposal_id, "reason": "Stale content hash"})
            return PatchValidationResult(
                success=False,
                proposal_id=proposal_id,
                error_message="Stale content hash: file was modified concurrently since proposal was generated.",
            )

        content = current_bytes.decode("utf-8", errors="replace")
        lines = content.splitlines(keepends=True)

        # 4. Ambiguity & Target Snippet Matching
        matched_line_idx, match_err = self._locate_target_snippet(
            lines=lines,
            start_line=proposal.start_line,
            end_line=proposal.end_line,
            target_snippet=proposal.target_snippet,
        )
        if match_err:
            return PatchValidationResult(
                success=False,
                proposal_id=proposal_id,
                error_message=match_err,
            )

        # 5. In-Memory Patch & Syntax Pre-Validation
        patched_lines = list(lines)
        target_line = lines[matched_line_idx]
        indent = target_line[: len(target_line) - len(target_line.lstrip())]

        replacement_lines = [
            (indent + l if not l.startswith(indent) else l) + "\n"
            for l in proposal.replacement_code.splitlines()
        ]
        if not replacement_lines:
            replacement_lines = ["\n"]

        patched_lines[matched_line_idx : matched_line_idx + 1] = replacement_lines
        patched_content = "".join(patched_lines)

        # Check Python Syntax before disk write
        if safe_path.suffix == ".py":
            try:
                ast.parse(patched_content)
            except SyntaxError as syn_err:
                _log_event("REMEDIATION_FAILED", "HIGH", {"proposal_id": proposal_id, "reason": f"Syntax error: {syn_err}"})
                return PatchValidationResult(
                    success=False,
                    proposal_id=proposal_id,
                    error_message=f"Invalid Python syntax in patch: {syn_err.msg} at line {syn_err.lineno}",
                )

        # 6. Create Atomic Backup File
        backup_path = safe_path.with_suffix(safe_path.suffix + ".devwatch_backup")
        try:
            shutil.copy2(safe_path, backup_path)
        except Exception as err:
            return PatchValidationResult(
                success=False,
                proposal_id=proposal_id,
                error_message=f"Failed to create backup file: {err}",
            )

        # 7. Write Patch Atomically
        try:
            safe_path.write_text(patched_content, encoding="utf-8")
        except Exception as write_err:
            if backup_path.exists():
                shutil.copy2(backup_path, safe_path)
                backup_path.unlink(missing_ok=True)
            return PatchValidationResult(
                success=False,
                proposal_id=proposal_id,
                error_message=f"Disk write error: {write_err}",
                rolled_back=True,
            )

        # 8. Post-Application Validation & Rollback if Failed
        try:
            if safe_path.suffix == ".py":
                disk_code = safe_path.read_text(encoding="utf-8")
                ast.parse(disk_code)
                self.ast_tool.analyze_file(file_path, disk_code)
        except Exception as post_err:
            logger.warning(f"Post-patch validation failed for {file_path}: {post_err}. Rolling back!")
            if backup_path.exists():
                shutil.copy2(backup_path, safe_path)
                backup_path.unlink(missing_ok=True)
            _log_event("REMEDIATION_ROLLED_BACK", "HIGH", {"proposal_id": proposal_id, "file_path": file_path, "reason": str(post_err)})
            return PatchValidationResult(
                success=False,
                proposal_id=proposal_id,
                error_message=f"Post-application validation failed: {post_err}. Patch rolled back.",
                backup_created=True,
                rolled_back=True,
            )


        # Clean up backup on successful application
        backup_path.unlink(missing_ok=True)

        proposal.status = ProposalStatus.APPLIED
        diff = "".join(difflib.unified_diff(lines, patched_lines, fromfile=file_path, tofile=file_path))

        _log_event(
            "REMEDIATION_APPLIED",
            "INFO",
            {
                "proposal_id": proposal_id,
                "finding_id": proposal.finding_id,
                "file_path": file_path,
                "authorized_by": authorized_by,
            },
        )

        return PatchValidationResult(
            success=True,
            proposal_id=proposal_id,
            diff_preview=diff,
            backup_created=True,
            rolled_back=False,
        )

    def _locate_target_snippet(
        self, lines: List[str], start_line: int, end_line: int, target_snippet: str
    ) -> Tuple[int, Optional[str]]:
        clean_target = target_snippet.strip()
        if not clean_target:
            idx = max(0, min(start_line - 1, len(lines) - 1)) if lines else 0
            return idx, None

        # Check exact line match around start_line (+/- 5 line window)
        target_idx = start_line - 1
        matches_in_file = [i for i, l in enumerate(lines) if clean_target in l.strip()]

        if not matches_in_file:
            return -1, f"Target snippet '{clean_target[:30]}...' not found in file."

        if len(matches_in_file) == 1:
            return matches_in_file[0], None

        # Multiple matches exist -> check if one match falls cleanly within start_line +/- 5 lines
        nearby_matches = [idx for idx in matches_in_file if abs(idx - target_idx) <= 5]
        if len(nearby_matches) == 1:
            return nearby_matches[0], None

        return -1, f"Ambiguous match: target snippet '{clean_target[:30]}...' occurs {len(matches_in_file)} times in file."

    def _generate_diff(
        self, file_path: str, lines: List[str], start_line: int, end_line: int, target_snippet: str, replacement_code: str
    ) -> str:
        idx, _ = self._locate_target_snippet(lines, start_line, end_line, target_snippet)
        if idx < 0:
            idx = max(0, min(start_line - 1, len(lines) - 1)) if lines else 0

        target_line = lines[idx] if lines else ""
        indent = target_line[: len(target_line) - len(target_line.lstrip())]

        repl_lines = [
            (indent + l if not l.startswith(indent) else l) + "\n"
            for l in replacement_code.splitlines()
        ]

        patched = list(lines)
        patched[idx : idx + 1] = repl_lines

        return "".join(difflib.unified_diff(lines, patched, fromfile=f"a/{file_path}", tofile=f"b/{file_path}"))
