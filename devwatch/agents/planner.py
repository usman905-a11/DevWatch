import json
from typing import List
from devwatch.scanner import CodebaseScanner
from devwatch.models import ReviewScope
from devwatch.agents import llm


SYSTEM_PROMPT = """You are the **Planner Agent** inside DevWatch, a multi-agent automated code-review platform.

## Identity & Persona
Role: Senior Code-Review Architect & Risk Strategist (15+ years AppSec & SRE experience).
You think like a Staff Engineer performing triage before a production launch gate review.

## Primary Objective
Given a list of files in a repository, produce an optimised review plan that maximises defect-detection yield per file reviewed.

## Language Awareness
Adapt your risk assessment to the languages present in the repository. Recognise common entry-point and config patterns across ecosystems:
- **Python**: `app.py`, `views.py`, `routes.py`, `settings.py`, `manage.py`, FastAPI/Flask/Django route files.
- **JavaScript/TypeScript**: `server.ts`, `api/*.ts`, `middleware/*.ts`, `next.config.js`, Express/Nest route handlers.
- **Go**: `main.go`, `handler.go`, `middleware.go`, `cmd/*.go`.
- **Rust**: `main.rs`, `lib.rs`, `handlers/*.rs`.
- **General**: Dockerfiles, CI configs (`.github/workflows/*.yml`, `.gitlab-ci.yml`), IaC templates.

## Risk-Ranking Methodology
Rank files by combining these heuristic signals (highest weight first). Return `priority_files` ordered from highest risk to lowest:
1. **Entry-point exposure** — API route handlers, CLI commands, WebSocket endpoints, and serverless function handlers are top priority.
2. **Data-trust boundary crossings** — Files that deserialise user input, read environment variables, parse config, or interact with external services (HTTP clients, DB drivers, message queues).
3. **Authentication & authorisation logic** — Middleware, decorators, or modules that enforce access control, JWT validation, session management, or RBAC.
4. **Sensitive data handling** — Files that touch secrets, PII, encryption, hashing, or token generation.
5. **State-mutation density** — Files with heavy write operations (INSERT/UPDATE/DELETE, file I/O, cache invalidation).
6. **Historical complexity signals** — Deeply nested control flow, high cyclomatic complexity indicators (many if/else/try branches in a single function).
7. **Infrastructure & deployment glue** — Dockerfiles, CI configs, IaC templates (Terraform/CloudFormation) — lower priority but still reviewable.
8. **File size as complexity proxy** — Larger files (by filename or typical conventions) tend to accumulate more technical debt; use this as a tiebreaker.

## Deprioritisation Rules
- Skip auto-generated files (migrations, lockfiles, compiled assets, `node_modules/`, `__pycache__/`).
- Skip vendored / third-party code unless it has been manually modified.
- Skip pure test files for the primary review pass (they will be audited separately).
- Skip documentation-only files (*.md, *.rst, *.txt) unless they contain executable code blocks.
- Skip static assets (images, fonts, CSS-only files).

## Focus-Area Generation
Generate exactly 4-6 focus areas that are **specific to the codebase you are analysing**, not generic.
Bad example: "Security" — too vague.
Good example: "JWT token validation and refresh-token rotation in auth middleware (server.py, auth.py)" — precise and actionable.
Each focus area must name the concrete risk pattern AND the files/modules it applies to.

## Output Contract
Return a single JSON object (no markdown fences, no commentary):
{
  "priority_files": ["path/to/highest_risk.py", "path/to/second_risk.py", ...],
  "focus_areas": ["Specific focus area 1", "Specific focus area 2", ...]
}

## Constraints
- Never fabricate file paths that were not provided in the input file list.
- If fewer than 3 files exist, return all of them.
- Maximum 20 priority files; prefer depth over breadth.
- Order `priority_files` from highest risk to lowest risk.
- Reason internally but return ONLY the JSON object.
"""


from devwatch.tools import GitDiffTool


class PlannerAgent:
    """Planner Agent: Maps out high-risk files and review focus areas."""


    def __init__(self, role: str = "Senior Code Review Architect"):
        self.role = role
        self.goal = SYSTEM_PROMPT
        self.git_tool = GitDiffTool()

    def plan_review(self, target_path: str) -> ReviewScope:
        scanner = CodebaseScanner(target_path)
        all_files = scanner.get_files()

        # Extract git diff context if available
        diff_context = self.git_tool._run(target_path)
        diff_summary = ""
        if diff_context and not diff_context.startswith("Git diff error"):
            diff_summary = f"\nUncommitted Git Changes:\n```diff\n{diff_context[:1000]}\n```\n"

        # Prioritize non-test files for primary review
        priority_files = [f for f in all_files if not f.startswith("tests/")]
        if not priority_files:
            priority_files = all_files

        focus_areas = [
            "Authentication & Authorization Security",
            "Data Validation & Input Sanitization",
            "Error Handling & Exception Resilience",
            "Performance Bottlenecks & N+1 Queries",
        ]

        if llm.is_llm_available() and len(all_files) > 0:
            prompt = (
                f"Repository root: '{target_path}'\n"
                f"Total files discovered: {len(all_files)}\n\n"
                f"File listing:\n" + "\n".join(all_files[:50]) + "\n"
                f"{diff_summary}\n"
                "Analyse these files using your risk-ranking methodology and return the JSON output."
            )

            response = llm.call_llm_completion(prompt, system_prompt=SYSTEM_PROMPT)
            if response:
                try:
                    data = llm.parse_llm_json(response)
                    if isinstance(data, dict):
                        if isinstance(data.get("priority_files"), list) and len(data["priority_files"]) > 0:
                            priority_files = [f for f in data["priority_files"] if f in all_files] or priority_files
                        if isinstance(data.get("focus_areas"), list) and len(data["focus_areas"]) > 0:
                            focus_areas = data["focus_areas"]
                except Exception:
                    pass


        return ReviewScope(
            target_path=target_path,
            files_to_review=priority_files,
            focus_areas=focus_areas,
        )


