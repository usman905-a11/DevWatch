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
Produce a structured review plan that downstream agents can execute within their context budget. For each unit of work:
1. Identify a scoped group of files (by module, feature, or directory) small enough to fit comfortably in one agent call
2. Assign a priority: critical_path (auth, payment, data access, external input handling), standard, or low_priority (tests, generated code, vendored dependencies, config)
3. Note any cross-file dependencies the reviewing agent will need (e.g., "auth.py imports helpers from utils/crypto.py — include both")
4. Flag files that exceed a reasonable single-call size and should be chunked by function/class rather than passed whole

Do not skip files by silently truncating the list. If the codebase is too large to plan for in full detail, say so explicitly and propose a batching strategy (e.g., "plan module-by-module; request the next module's file list once the current one is reviewed") rather than dropping files without saying so.

OUTPUT FORMAT
Return a JSON object matching the ReviewPlan schema:
{
  "priority_files": ["relative/path/1.py", "relative/path/2.py"],
  "focus_areas": ["OWASP Top 10", "SQL Injection", "Error Handling"]
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


