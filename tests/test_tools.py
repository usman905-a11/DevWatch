import os
import pytest
from devwatch.scanner import CodebaseScanner
from devwatch.tools import (
    CodebaseScannerTool,
    GitDiffTool,
    SecurityPatternTool,
    LogicAnalyzerTool,
    IssueDeduplicatorTool,
)
from devwatch.models import CodeIssue, IssueSeverity

def test_scanner_collects_code_files(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "utils.js").write_text("console.log('hi');")
    (tmp_path / "ignored.pyc").write_bytes(b"\x00\x01\x02")
    
    node_dir = tmp_path / "node_modules"
    node_dir.mkdir()
    (node_dir / "dep.js").write_text("var x = 1;")

    scanner = CodebaseScanner(str(tmp_path))
    files = scanner.get_files()

    assert "main.py" in files
    assert "utils.js" in files
    assert "ignored.pyc" not in files
    assert "node_modules/dep.js" not in files

def test_scanner_reads_file(tmp_path):
    (tmp_path / "test.py").write_text("def hello(): pass")
    scanner = CodebaseScanner(str(tmp_path))
    content = scanner.read_file("test.py")
    assert content == "def hello(): pass"

def test_security_pattern_tool():
    tool = SecurityPatternTool()
    vulnerable_code = "SECRET_KEY = 'sk_live_1234567890abcdef1234'\ncursor.execute(f'SELECT * FROM users WHERE id = {user_id}')"
    issues = tool._run(file_path="config.py", code_content=vulnerable_code)
    
    assert len(issues) >= 2
    assert any(i.severity == IssueSeverity.CRITICAL for i in issues)
    assert any(i.severity == IssueSeverity.HIGH for i in issues)

def test_logic_analyzer_tool():
    tool = LogicAnalyzerTool()
    flawed_code = "try:\n    do_something()\nexcept:\n    pass\nprint('debug statement')\n"
    issues = tool._run(file_path="app.py", code_content=flawed_code)
    
    assert len(issues) >= 2
    assert any("Except" in i.title for i in issues)
    assert any("Print" in i.title for i in issues)

def test_issue_deduplicator_tool():
    tool = IssueDeduplicatorTool()
    issue1 = CodeIssue(
        file_path="app.py", line_number=10, severity=IssueSeverity.HIGH,
        category="Security", title="SQL Injection", description="Raw SQL", suggestion="Use ORM"
    )
    issue2 = CodeIssue(
        file_path="app.py", line_number=10, severity=IssueSeverity.HIGH,
        category="Security", title="SQL Injection", description="Raw SQL duplicate", suggestion="Use ORM"
    )
    deduped = tool._run(issues=[issue1, issue2])
    assert len(deduped) == 1
    assert deduped[0].file_path == "app.py"
