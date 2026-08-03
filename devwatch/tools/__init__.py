import re
import ast
import git
from typing import List, Dict, Any, Optional
from devwatch.scanner import CodebaseScanner
from devwatch.models import CodeIssue, IssueSeverity


class CodebaseScannerTool:
    name: str = "CodebaseScannerTool"
    description: str = "Scans target directory files and reads source code."

    def _run(self, root_dir: str, file_path: Optional[str] = None) -> Any:
        scanner = CodebaseScanner(root_dir)
        if file_path:
            return scanner.read_file(file_path)
        return scanner.get_files()


class GitDiffTool:
    name: str = "GitDiffTool"
    description: str = "Extracts git diff for modified files in target repository."

    def _run(self, repo_path: str) -> str:
        try:
            repo = git.Repo(repo_path, search_parent_directories=True)
            diff_text = repo.git.diff("HEAD")
            if not diff_text:
                diff_text = "No uncommitted git changes found."
            return diff_text
        except Exception as e:
            return f"Git diff error: {str(e)}"


class SecurityPatternTool:
    name: str = "SecurityPatternTool"
    description: str = "Scans code for OWASP vulnerabilities, hardcoded secret keys, and SQL injection flaws."

    def _run(self, file_path: str, code_content: str) -> List[CodeIssue]:
        issues = []
        lines = code_content.splitlines()

        secret_pattern = re.compile(
            r".*(SECRET|PASSWORD|TOKEN|API_KEY|AWS_KEY|PRIVATE_KEY).*\s*=\s*['\"][A-Za-z0-9_\-]{8,}['\"]",
            re.IGNORECASE,
        )
        sql_pattern = re.compile(
            r"(execute|query)\s*\(\s*f['\"].*(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)",
            re.IGNORECASE,
        )

        for idx, line in enumerate(lines, 1):
            if secret_pattern.search(line):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.CRITICAL,
                        category="Security",
                        title="Hardcoded Secret Credential",
                        description="Plaintext secret or API key credential found in source code.",
                        suggestion="Store credentials in environment variables or a secret vault.",
                        code_snippet=line.strip(),
                    )
                )
            if sql_pattern.search(line):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.HIGH,
                        category="Security",
                        title="Potential SQL Injection Vulnerability",
                        description="Raw string formatting used inside SQL query execution.",
                        suggestion="Use parameterized query parameters or ORM abstractions.",
                        code_snippet=line.strip(),
                    )
                )

        return issues


class LogicAnalyzerTool:
    name: str = "LogicAnalyzerTool"
    description: str = "Scans code for runtime exception risks, unhandled try/except blocks, and leftover debug code."

    def _run(self, file_path: str, code_content: str) -> List[CodeIssue]:
        issues = []
        lines = code_content.splitlines()

        bare_except_pattern = re.compile(r"^\s*except\s*:\s*$", re.IGNORECASE)
        print_pattern = re.compile(r"^\s*print\(", re.IGNORECASE)

        for idx, line in enumerate(lines, 1):
            if bare_except_pattern.search(line):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.MEDIUM,
                        category="Code Quality",
                        title="Bare Except Clause Detected",
                        description="Catching all exceptions silently can mask critical system errors.",
                        suggestion="Catch specific exception types (e.g., ValueError, KeyError).",
                        code_snippet=line.strip(),
                    )
                )
            if print_pattern.search(line) and not file_path.endswith("cli.py"):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.LOW,
                        category="Code Quality",
                        title="Leftover Debug Print Statement",
                        description="Raw print statement found in source file.",
                        suggestion="Replace print statement with structured logging.",
                        code_snippet=line.strip(),
                    )
                )

        return issues


class IssueDeduplicatorTool:
    name: str = "IssueDeduplicatorTool"
    description: str = "Deduplicates issues by file path & line number and sorts by severity."

    def _run(self, issues: List[CodeIssue]) -> List[CodeIssue]:
        seen = set()
        unique_issues = []

        severity_rank = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.HIGH: 1,
            IssueSeverity.MEDIUM: 2,
            IssueSeverity.LOW: 3,
            IssueSeverity.INFO: 4,
        }

        for issue in issues:
            key = (issue.file_path, issue.line_number, issue.title)
            if key not in seen:
                seen.add(key)
                unique_issues.append(issue)

        unique_issues.sort(key=lambda i: severity_rank.get(i.severity, 99))
        return unique_issues
