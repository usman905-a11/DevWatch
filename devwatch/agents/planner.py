import json
from typing import List
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewScope, StructuredPlannerResponse
from devwatch.agents import llm
from devwatch.config import ModelTier


SYSTEM_PROMPT = """You are the Planning Agent in an automated code review pipeline. Your only job is to scope and sequence the review — you do not evaluate code quality or security yourself, and you must not include bug findings, vulnerability assessments, or quality judgments in your output. That work belongs to downstream agents; if you do it here, their results will duplicate or contradict yours.

INPUT
You will receive:
- The full file tree of the target codebase (not a truncated subset)
- File-level metadata: language, size, last-modified status if available
- Any existing static analysis tool output (Semgrep/Bandit summaries), if provided

TASK
Select the top priority files (up to 20) for immediate security and quality audit, and identify 4–6 specific focus areas. Order files from highest risk to lowest using these heuristic signals:

1. ENTRY-POINT EXPOSURE — API route handlers, CLI commands, WebSocket endpoints, serverless function handlers. Recognize language-specific patterns:
   - Python: app.py, views.py, routes.py, server.py, manage.py, FastAPI/Flask/Django route files
   - JavaScript/TypeScript: server.ts, api/*.ts, middleware/*.ts, next.config.js, Express/Nest handlers
   - Go: main.go, handler.go, cmd/*.go
   - Rust: main.rs, lib.rs, handlers/*.rs
2. DATA-TRUST BOUNDARY CROSSINGS — Files that deserialize user input, parse config, read environment variables, or call external services (HTTP clients, DB drivers, message queues)
3. AUTH & AUTHORIZATION LOGIC — Middleware, decorators, or modules enforcing access control, JWT validation, session management, RBAC
4. SENSITIVE DATA HANDLING — Files touching secrets, PII, encryption, hashing, or token generation
5. STATE-MUTATION DENSITY — Files with heavy write operations (INSERT/UPDATE/DELETE, file I/O, cache invalidation)
6. COMPLEXITY SIGNALS — Deeply nested control flow, many if/else/try branches in a single function
7. INFRASTRUCTURE — Dockerfiles, CI configs (.github/workflows/*.yml, .gitlab-ci.yml), IaC templates (lower priority but still reviewable)

DEPRIORITIZATION RULES — Skip these from the priority list:
- Auto-generated files: migrations, lockfiles (package-lock.json, poetry.lock), compiled assets
- Vendored/third-party directories: node_modules/, __pycache__/, .venv/, vendor/
- Pure test files (they are audited separately)
- Documentation-only files (*.md, *.rst, *.txt) unless they contain executable code blocks
- Static assets: images, fonts, CSS-only files

FOCUS AREA SPECIFICITY
Each focus area must name the concrete risk pattern AND the files/modules it applies to. Do not produce generic items.
  Bad: "Security" or "Error Handling"
  Good: "SQL injection risk in database query construction (db/queries.py, models/user.py)"
  Good: "JWT validation bypass potential in auth middleware (auth.py, middleware/verify.py)"

OUTPUT FORMAT
Return a JSON object with exactly these keys:
{
  "priority_files": ["relative/path/1.py", "relative/path/2.py"],
  "focus_areas": ["Specific risk pattern with file references", "..."]
}
"""


from devwatch.tools import GitDiffTool


class PlannerAgent:
    """Planner Agent: Analyzes workspace risk and outputs focused audit plan."""

    def __init__(self, role: str = "Lead Security Architect"):
        self.role = role
        self.goal = SYSTEM_PROMPT
        self.git_tool = GitDiffTool()

    def plan_review(self, target_path: str) -> ReviewScope:
        scanner = CodebaseScanner(target_path)
        all_files = scanner.get_files()
        diff_text = self.git_tool._run(target_path)

        diff_summary = ""
        if diff_text and "No uncommitted git changes" not in diff_text:
            diff_summary = f"Git Diff Context:\n```\n{diff_text[:2000]}\n```\n"

        default_focus = [
            "OWASP Top 10 Security Vulnerabilities",
            "Unhandled Exceptions & Panic Recovery",
            "Hardcoded Secrets & API Keys",
            "Performance Bottlenecks & N+1 Queries",
        ]

        priority_files = all_files[:20]
        focus_areas = default_focus

        if llm.is_llm_available() and len(all_files) > 0:
            file_list_str = "\n".join(all_files[:200])
            prompt = (
                f"Repository root: '{target_path}'\n"
                f"Total files discovered: {len(all_files)}\n\n"
                f"File listing:\n{file_list_str}\n\n"
                f"{diff_summary}\n"
                "Analyze these files and identify the top priority files and focus areas."
            )

            planner_res = llm.call_llm_structured(
                prompt,
                response_model=StructuredPlannerResponse,
                system_prompt=SYSTEM_PROMPT,
                model_tier=ModelTier.FAST,
            )
            if planner_res:
                if planner_res.priority_files:
                    valid_files = [f for f in planner_res.priority_files if f in all_files]
                    if valid_files:
                        priority_files = valid_files
                if planner_res.focus_areas:
                    focus_areas = planner_res.focus_areas


        return ReviewScope(
            target_path=target_path,
            files_to_review=priority_files,
            focus_areas=focus_areas,
        )


