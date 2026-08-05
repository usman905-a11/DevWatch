import pytest
import ast
from pathlib import Path
from unittest.mock import patch, MagicMock
from devwatch.patcher import RemediationPatcher
from devwatch.models import RemediationProposal, ProposalStatus


@pytest.fixture
def patcher_env(tmp_path):
    repo = tmp_path / "workspace"
    repo.mkdir()
    return repo


def test_valid_exact_patch_with_diff_preview(patcher_env):
    target_file = patcher_env / "app.py"
    target_file.write_text("import sys\nprint('hello')\nx = 1\n", encoding="utf-8")

    patcher = RemediationPatcher(str(patcher_env))
    proposal = patcher.propose_fix(
        file_path="app.py",
        finding_id="f1",
        start_line=2,
        end_line=2,
        target_snippet="print('hello')",
        replacement_code="logger.info('hello')",
        reason="Replace debug print with logging",
        author="agent",
    )

    assert proposal.expected_content_hash is not None
    assert "-print('hello')" in proposal.diff_preview
    assert "+logger.info('hello')" in proposal.diff_preview

    result = patcher.apply_proposal(proposal, authorized_by="user_123")
    assert result.success is True
    assert "logger.info('hello')" in target_file.read_text(encoding="utf-8")
    assert not (patcher_env / "app.py.devwatch_backup").exists()


def test_duplicate_snippets_rejected_as_ambiguous(patcher_env):
    target_file = patcher_env / "utils.py"
    target_file.write_text("print('test')\nx = 1\nprint('test')\ny = 2\n", encoding="utf-8")

    patcher = RemediationPatcher(str(patcher_env))
    proposal = patcher.propose_fix(
        file_path="utils.py",
        finding_id="f2",
        start_line=1,
        end_line=1,
        target_snippet="print('test')",
        replacement_code="logger.debug('test')",
        reason="Clean print",
    )

    result = patcher.apply_proposal(proposal, authorized_by="user_123")
    assert result.success is False
    assert "Ambiguous match" in result.error_message


def test_shifted_lines_uniquely_matched(patcher_env):
    target_file = patcher_env / "server.py"
    # Target line is at line 15 instead of expected line 2
    content = "import os\n" + "\n" * 12 + "secret_token = 'sk-123456'\n"
    target_file.write_text(content, encoding="utf-8")

    patcher = RemediationPatcher(str(patcher_env))
    proposal = patcher.propose_fix(
        file_path="server.py",
        finding_id="f3",
        start_line=2,
        end_line=2,
        target_snippet="secret_token = 'sk-123456'",
        replacement_code="secret_token = os.getenv('TOKEN')",
        reason="Redact hardcoded token",
    )

    result = patcher.apply_proposal(proposal, authorized_by="user_123")
    assert result.success is True
    assert "os.getenv('TOKEN')" in target_file.read_text(encoding="utf-8")


def test_stale_content_hash_rejected(patcher_env):
    target_file = patcher_env / "db.py"
    target_file.write_text("query = 'SELECT 1'\n", encoding="utf-8")

    patcher = RemediationPatcher(str(patcher_env))
    proposal = patcher.propose_fix(
        file_path="db.py",
        finding_id="f4",
        start_line=1,
        end_line=1,
        target_snippet="query = 'SELECT 1'",
        replacement_code="query = 'SELECT 2'",
        reason="Fix query",
    )

    # Concurrently modify file before applying proposal
    target_file.write_text("query = 'SELECT CONCURRENT'\n", encoding="utf-8")

    result = patcher.apply_proposal(proposal, authorized_by="user_123")
    assert result.success is False
    assert "Stale content hash" in result.error_message


def test_invalid_python_syntax_rejected(patcher_env):
    target_file = patcher_env / "calc.py"
    target_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    patcher = RemediationPatcher(str(patcher_env))
    proposal = patcher.propose_fix(
        file_path="calc.py",
        finding_id="f5",
        start_line=2,
        end_line=2,
        target_snippet="return a + b",
        replacement_code="return a + (invalid syntax ++--",
        reason="Broken patch",
    )

    result = patcher.apply_proposal(proposal, authorized_by="user_123")
    assert result.success is False
    assert "Invalid Python syntax" in result.error_message
    assert "return a + b" in target_file.read_text(encoding="utf-8")


def test_unauthorized_request_rejected(patcher_env):
    target_file = patcher_env / "main.py"
    target_file.write_text("x = 1\n", encoding="utf-8")

    patcher = RemediationPatcher(str(patcher_env))
    proposal = patcher.propose_fix(
        file_path="main.py",
        finding_id="f6",
        start_line=1,
        end_line=1,
        target_snippet="x = 1",
        replacement_code="x = 2",
        reason="Update x",
    )

    result = patcher.apply_proposal(proposal, authorized_by="")
    assert result.success is False
    assert "Unauthorized" in result.error_message


def test_path_traversal_attempt_rejected(patcher_env):
    patcher = RemediationPatcher(str(patcher_env))

    with pytest.raises(ValueError, match="Path traversal attempt blocked"):
        patcher.propose_fix(
            file_path="../etc_passwd.py",
            finding_id="f7",
            start_line=1,
            end_line=1,
            target_snippet="root",
            replacement_code="nobody",
            reason="Hack attempt",
        )



def test_post_validation_failure_triggers_rollback(patcher_env):
    target_file = patcher_env / "service.py"
    original_text = "def run():\n    pass\n"
    target_file.write_text(original_text, encoding="utf-8")

    patcher = RemediationPatcher(str(patcher_env))
    proposal = patcher.propose_fix(
        file_path="service.py",
        finding_id="f8",
        start_line=2,
        end_line=2,
        target_snippet="pass",
        replacement_code="do_work()",
        reason="Implement service",
    )

    # Mock ast_tool.analyze_file to raise RuntimeError during post-application validation
    with patch.object(patcher.ast_tool, "analyze_file", side_effect=RuntimeError("Post-validation static check failed")):
        result = patcher.apply_proposal(proposal, authorized_by="admin")

        assert result.success is False
        assert result.rolled_back is True
        assert target_file.read_text(encoding="utf-8") == original_text
        assert not (patcher_env / "service.py.devwatch_backup").exists()

