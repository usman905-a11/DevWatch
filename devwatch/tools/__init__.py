import re
import ast
try:
    import git
except ImportError:
    git = None

from typing import List, Dict, Any, Optional
from devwatch.models import CodeIssue, IssueSeverity


def redact_secret_in_snippet(snippet: Optional[str]) -> Optional[str]:
    """Redact literal secret key/token values in code snippets before storing in reports or logs."""
    if not snippet:
        return snippet
    # Redact quoted secret assignments: KEY = 'secret...'
    redacted = re.sub(
        r"((?:SECRET|PASSWORD|TOKEN|API_KEY|AWS_KEY|PRIVATE_KEY|KEY|AUTH|CREDENTIAL)[A-Za-z0-9_\-]*\s*=\s*)(['\"])[^'\"]+(['\"])",
        r"\1\2[REDACTED_SECRET]\3",
        snippet,
        flags=re.IGNORECASE,
    )
    # Redact raw secret tokens (e.g. sk-..., akia..., ghp_...)
    redacted = re.sub(
        r"\b(sk-[A-Za-z0-9_\-]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36})\b",
        "[REDACTED_SECRET]",
        redacted,
    )
    return redacted


class GitDiffTool:
    name: str = "GitDiffTool"
    description: str = "Extracts git diff for modified files in target repository."

    def _run(self, repo_path: str) -> str:
        if git is None:
            return "Git diff disabled (gitpython package not installed)."
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
    description: str = "Scans code for OWASP vulnerabilities, secret keys, injection, and unsafe calls."

    def _run(self, file_path: str, code_content: str) -> List[CodeIssue]:
        issues = []
        lines = code_content.splitlines()

        secret_pattern = re.compile(
            r".*(SECRET|PASSWORD|TOKEN|API_KEY|AWS_KEY|PRIVATE_KEY).*\s*=\s*['\"][A-Za-z0-9_\-]{8,}['\"]",
            re.IGNORECASE,
        )
        sql_pattern = re.compile(
            r"((execute|query)\s*\(\s*f['\"]|.*(sql|query|stmt|cmd)\s*=\s*f['\"]).*(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)",
            re.IGNORECASE,
        )
        eval_pattern = re.compile(r"\b(eval|exec)\s*\(", re.IGNORECASE)
        cmd_pattern = re.compile(r"\b(os\.system|subprocess\.(call|Popen|run).*shell\s*=\s*True)", re.IGNORECASE)
        deserial_pattern = re.compile(r"\b(pickle\.loads|yaml\.load)\s*\(", re.IGNORECASE)
        debug_pattern = re.compile(r"\bDEBUG\s*=\s*True\b", re.IGNORECASE)

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
                        code_snippet=redact_secret_in_snippet(line.strip()),
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
            if eval_pattern.search(line):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.CRITICAL,
                        category="Security",
                        title="Dynamic Code Execution (eval/exec)",
                        description="Executing untrusted strings as code can lead to Remote Code Execution.",
                        suggestion="Avoid eval/exec; use safe parsing or explicit dictionary lookups.",
                        code_snippet=line.strip(),
                    )
                )
            if cmd_pattern.search(line):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.HIGH,
                        category="Security",
                        title="Potential OS Command Injection",
                        description="Invoking shell commands with shell=True can allow arbitrary command execution.",
                        suggestion="Pass command arguments as a list without shell=True.",
                        code_snippet=line.strip(),
                    )
                )
            if deserial_pattern.search(line):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.HIGH,
                        category="Security",
                        title="Insecure Deserialization Risk",
                        description="Unsafe deserialization (pickle/yaml) can execute arbitrary objects.",
                        suggestion="Use yaml.safe_load() or JSON for safe serialization.",
                        code_snippet=line.strip(),
                    )
                )
            if debug_pattern.search(line):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.MEDIUM,
                        category="Security",
                        title="Production Debug Mode Enabled",
                        description="Running in debug mode leaks sensitive stack traces and credentials.",
                        suggestion="Disable DEBUG mode in production environments via environment variables.",
                        code_snippet=line.strip(),
                    )
                )

        return issues


class LogicAnalyzerTool:
    name: str = "LogicAnalyzerTool"
    description: str = "Scans code for runtime exception risks, unhandled errors, long functions, and debug code."

    def _run(self, file_path: str, code_content: str) -> List[CodeIssue]:
        issues = []
        lines = code_content.splitlines()

        bare_except_pattern = re.compile(r"^\s*except\s*:\s*$", re.IGNORECASE)
        print_pattern = re.compile(r"^\s*print\(", re.IGNORECASE)
        todo_pattern = re.compile(r"#\s*(TODO|FIXME|HACK)\b", re.IGNORECASE)
        request_no_timeout = re.compile(r"requests\.(get|post|put|delete)\([^)]*\)", re.IGNORECASE)

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
            if todo_pattern.search(line):
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.INFO,
                        category="Code Quality",
                        title="Unresolved Developer Note (TODO/FIXME)",
                        description="Developer note left in production code.",
                        suggestion="Track resolution in issue tracker and address before release.",
                        code_snippet=line.strip(),
                    )
                )
            if request_no_timeout.search(line) and "timeout" not in line:
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.MEDIUM,
                        category="Code Quality",
                        title="HTTP Request Missing Timeout",
                        description="HTTP client calls without timeouts can block workers indefinitely.",
                        suggestion="Pass explicit timeout parameter (e.g., timeout=10).",
                        code_snippet=line.strip(),
                    )
                )

        # AST analysis for Python files
        if file_path.endswith(".py"):
            try:
                tree = ast.parse(code_content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_lines = node.end_lineno - node.lineno + 1 if hasattr(node, "end_lineno") else 0
                        if func_lines > 50:
                            issues.append(
                                CodeIssue(
                                    file_path=file_path,
                                    line_number=node.lineno,
                                    severity=IssueSeverity.LOW,
                                    category="Code Quality",
                                    title=f"God Function Detected ({node.name})",
                                    description=f"Function '{node.name}' spans {func_lines} lines, exceeding 50 line threshold.",
                                    suggestion="Refactor function into smaller single-responsibility functions.",
                                    code_snippet=f"def {node.name}(...): ({func_lines} lines)",
                                )
                            )
            except Exception:
                pass

        return issues


class IssueDeduplicatorTool:
    name: str = "IssueDeduplicatorTool"
    description: str = "Deduplicates issues using stable finding identity, evidence fingerprints, and rule IDs while preserving distinct nearby issues."

    def _run(self, issues: List[CodeIssue]) -> List[CodeIssue]:
        unique_issues: List[CodeIssue] = []

        severity_rank = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.HIGH: 1,
            IssueSeverity.MEDIUM: 2,
            IssueSeverity.LOW: 3,
            IssueSeverity.INFO: 4,
        }

        for candidate in issues:
            candidate.ensure_identity()
            duplicate_found = False

            for idx, existing in enumerate(unique_issues):
                existing.ensure_identity()

                # Grouping rule 1: Exact finding_id match
                if candidate.finding_id and existing.finding_id and candidate.finding_id == existing.finding_id:
                    line_dist = abs((candidate.line_number or 0) - (existing.line_number or 0))
                    if candidate.line_number and existing.line_number and line_dist > 3 and not candidate.code_snippet:
                        continue
                    duplicate_found = True
                    self._merge_issues(unique_issues, idx, candidate, existing, severity_rank)
                    break

                # Skip comparison if file paths differ
                cand_path = candidate.file_path.replace("\\", "/").strip("./")
                exist_path = existing.file_path.replace("\\", "/").strip("./")
                if cand_path != exist_path:
                    continue

                # Grouping rule 2: Same normalized file path + same rule/CWE + same evidence fingerprint
                same_fingerprint = (
                    candidate.evidence_fingerprint
                    and existing.evidence_fingerprint
                    and candidate.evidence_fingerprint == existing.evidence_fingerprint
                )

                rule_cand = (candidate.rule_id or candidate.cwe_id or "").lower()
                rule_exist = (existing.rule_id or existing.cwe_id or "").lower()

                # If rule/CWE IDs are explicitly present and differ, they are distinct issues
                if rule_cand and rule_exist and rule_cand != rule_exist:
                    continue

                line_dist = abs((candidate.line_number or 0) - (existing.line_number or 0))

                # Exact fingerprint match with same rule OR nearby lines with same fingerprint
                if same_fingerprint and (rule_cand == rule_exist or line_dist <= 3) and (line_dist <= 3 or candidate.code_snippet):
                    duplicate_found = True
                    self._merge_issues(unique_issues, idx, candidate, existing, severity_rank)
                    break


            if not duplicate_found:
                unique_issues.append(candidate)

        unique_issues.sort(key=lambda i: (severity_rank.get(i.severity, 99), i.file_path, i.line_number or 0))
        return unique_issues

    def _merge_issues(
        self,
        unique_issues: List[CodeIssue],
        target_idx: int,
        candidate: CodeIssue,
        existing: CodeIssue,
        severity_rank: Dict[IssueSeverity, int],
    ) -> None:
        cand_rank = severity_rank.get(candidate.severity, 99)
        exist_rank = severity_rank.get(existing.severity, 99)

        # Merge metadata sources
        sources = existing.metadata.get("sources", [existing.source_type])
        if candidate.source_type not in sources:
            sources.append(candidate.source_type)

        if cand_rank < exist_rank or (cand_rank == exist_rank and candidate.confidence_score > existing.confidence_score):
            merged = candidate
            merged.metadata["sources"] = sources
            merged.confidence_score = max(candidate.confidence_score, existing.confidence_score)
            unique_issues[target_idx] = merged
        else:
            existing.metadata["sources"] = sources
            existing.confidence_score = max(candidate.confidence_score, existing.confidence_score)


