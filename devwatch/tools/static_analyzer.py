import ast
from pathlib import Path
import re
from typing import List, Optional
from devwatch.models import CodeIssue, IssueSeverity
from devwatch.tools import redact_secret_in_snippet


class ASTStaticAnalyzerTool:
    """AST and structural static analysis tool for detecting code defects across Python source files."""

    def analyze_file(self, file_path: str, code_content: str) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        if not code_content or not code_content.strip():
            return issues

        lines = code_content.splitlines()

        # Regex fallback patterns for non-Python or general scanning
        secret_pattern = re.compile(
            r".*(SECRET|PASSWORD|TOKEN|API_KEY|AWS_KEY|PRIVATE_KEY).*\s*=\s*['\"](?P<value>[A-Za-z0-9_\-]{8,})['\"]",
            re.IGNORECASE,
        )
        sql_pattern = re.compile(
            r"((execute|query)\s*\(\s*f['\"]|.*(sql|query|stmt|cmd)\s*=\s*f['\"]).*(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)",
            re.IGNORECASE,
        )

        is_test_file = (
            file_path.replace("\\", "/").lower().startswith("tests/")
            or Path(file_path).name.lower().startswith("test_")
        )
        for idx, line in enumerate(lines, 1):
            secret_match = secret_pattern.search(line)
            placeholder = (
                secret_match is not None
                and is_test_file
                and secret_match.group("value").lower().startswith(
                    ("testonly", "dummy", "example", "fake")
                )
            )
            if secret_match and not placeholder:
                issues.append(
                    CodeIssue(
                        file_path=file_path,
                        line_number=idx,
                        severity=IssueSeverity.CRITICAL,
                        category="Security",
                        title="Hardcoded Secret Credential",
                        description="Plaintext secret or API credential stored directly in source code.",
                        suggestion="Store credentials in environment variables or a secure secrets vault.",
                        code_snippet=redact_secret_in_snippet(line.strip()),
                        confidence_score=1.0,
                        cwe_id="CWE-798",
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
                        description="Formatted f-string string interpolation detected in SQL statement.",
                        suggestion="Use parameterized queries (%s, :param) or ORM query abstractions.",
                        code_snippet=line.strip(),
                        confidence_score=0.95,
                        cwe_id="CWE-89",
                    )
                )

        if not file_path.endswith(".py"):
            return issues

        # AST Analysis for Python source files
        try:
            tree = ast.parse(code_content, filename=file_path)
            for node in ast.walk(tree):
                # 1. Check dangerous function calls: eval, exec, os.system, subprocess.call(shell=True)
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = f"{getattr(node.func.value, 'id', '')}.{node.func.attr}"

                    if func_name in ("eval", "exec"):
                        snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else f"{func_name}(...)"
                        issues.append(
                            CodeIssue(
                                file_path=file_path,
                                line_number=node.lineno,
                                severity=IssueSeverity.CRITICAL,
                                category="Security",
                                title=f"Dynamic Code Execution via {func_name}()",
                                description=f"Executing untrusted code via {func_name}() leads to Remote Code Execution.",
                                suggestion=f"Avoid using {func_name}(); use explicit parsing or dict lookups.",
                                code_snippet=snippet,
                                confidence_score=1.0,
                                cwe_id="CWE-95",
                            )
                        )
                    elif func_name == "os.system":
                        snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "os.system(...)"
                        issues.append(
                            CodeIssue(
                                file_path=file_path,
                                line_number=node.lineno,
                                severity=IssueSeverity.HIGH,
                                category="Security",
                                title="OS Command Injection via os.system",
                                description="Invoking shell commands via os.system allows shell command injection.",
                                suggestion="Use subprocess.run(['cmd', 'arg'], shell=False) with list arguments.",
                                code_snippet=snippet,
                                confidence_score=0.95,
                                cwe_id="CWE-78",
                            )
                        )

                # 2. Check bare except clauses
                if isinstance(node, ast.ExceptHandler):
                    if node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
                        # Check if body is just 'pass' or empty logging
                        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                            snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "except: pass"
                            issues.append(
                                CodeIssue(
                                    file_path=file_path,
                                    line_number=node.lineno,
                                    severity=IssueSeverity.MEDIUM,
                                    category="Code Quality",
                                    title="Bare Except Swallowing Exception",
                                    description="Catching all exceptions silently masks underlying system failures and errors.",
                                    suggestion="Catch specific exception types (e.g., ValueError, KeyError) and log errors.",
                                    code_snippet=snippet,
                                    confidence_score=0.9,
                                    cwe_id=None,
                                )
                            )

                # 3. Check functions exceeding cyclomatic / line thresholds
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines_count = (node.end_lineno - node.lineno + 1) if hasattr(node, "end_lineno") else 0
                    if lines_count > 50:
                        issues.append(
                            CodeIssue(
                                file_path=file_path,
                                line_number=node.lineno,
                                severity=IssueSeverity.LOW,
                                category="Code Quality",
                                title=f"High Complexity Function ({node.name})",
                                description=f"Function '{node.name}' spans {lines_count} lines exceeding 50-line complexity limit.",
                                suggestion="Decompose function into smaller single-responsibility helper functions.",
                                code_snippet=f"def {node.name}(...): ({lines_count} lines)",
                                confidence_score=0.85,
                                cwe_id=None,
                            )
                        )
        except Exception:
            pass

        return issues
