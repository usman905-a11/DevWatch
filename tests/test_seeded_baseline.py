"""Validate the seeded fixture repository, manifest, and baseline scorer."""

import asyncio
import json

import pytest

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.contracts import ModelTier
from scripts.run_seeded_scan import (
    DEFAULT_MANIFEST,
    DEFAULT_REPO,
    format_baseline_summary,
    load_seeded_manifest,
    match_seeded_issues,
    run_seeded_scan,
)


EXPECTED_CATEGORIES = {
    "bug_reliability",
    "logic_correctness",
    "quality_testability",
    "architecture_security",
    "performance_scalability",
}


def test_seeded_manifest_covers_all_five_categories_with_valid_lines():
    issues = load_seeded_manifest(DEFAULT_MANIFEST)
    assert 10 <= len(issues) <= 15
    assert {issue["category"] for issue in issues} == EXPECTED_CATEGORIES
    assert len({issue["id"] for issue in issues}) == len(issues)

    for issue in issues:
        source_path = DEFAULT_REPO / issue["file"]
        assert source_path.is_file(), f"Missing seeded file: {issue['file']}"
        lines = source_path.read_text(encoding="utf-8").splitlines()
        assert 1 <= issue["line"] <= issue.get("end_line", issue["line"]) <= len(lines)


def test_match_seeded_issues_reports_detecting_agent_missed_and_false_positives():
    issues = load_seeded_manifest(DEFAULT_MANIFEST)
    report = {
        "confirmed_defects": [
            {
                "finding_id": "f-sqli",
                "category": "architecture_security",
                "title": "SQL injection in find_user",
                "location": {"file_path": "auth_routes.py", "start_line": 14, "end_line": 14},
            }
        ],
        "uncertain_high_impact_candidates": [
            {
                "finding_id": "f-email",
                "category": "bug_reliability",
                "title": "Empty users list crash",
                "location": {"file_path": "orders.py", "start_line": 8, "end_line": 8},
            },
            {
                "finding_id": "f-fp",
                "category": "quality_testability",
                "title": "Unmatched style nit on docstring",
                "location": {"file_path": "orders.py", "start_line": 1, "end_line": 1},
            },
        ],
        "advisories": [],
        "verification_audit": {
            "provenance": {
                "f-sqli": {"task_id": "t-sec", "agent_id": "architecture_security"},
                "f-email": {"task_id": "t-bug", "agent_id": "bug_reliability"},
                "f-fp": {"task_id": "t-qual", "agent_id": "quality_testability"},
            }
        },
        "coverage": {"inspected_files": ["orders.py", "auth_routes.py"]},
    }

    summary = match_seeded_issues(issues, report)
    assert summary["seeded_total"] == len(issues)
    assert summary["found_count"] == 2
    assert summary["missed_count"] == len(issues) - 2
    assert summary["false_positive_count"] == 1
    found_by_id = {item["id"]: item for item in summary["found"]}
    assert found_by_id["SEED-01"]["found_by"] == ["bug_reliability"]
    assert found_by_id["SEED-05"]["found_by"] == ["architecture_security"]
    assert summary["false_positives"][0]["finding_id"] == "f-fp"
    assert summary["false_positives"][0]["agent_id"] == "quality_testability"

    rendered = format_baseline_summary(summary)
    assert "SEED-01" in rendered
    assert "architecture_security" in rendered
    assert "Unmatched style nit on docstring" in rendered


def test_run_seeded_scan_executes_against_seeded_repo_with_scripted_provider(tmp_path):
    class SeededScriptedProvider:
        async def generate_completion(self, request):
            data = json.loads(request.prompt)
            role = data["task"]["agent_id"]
            evidence = data["selected_context"]["evidence"]
            snapshot_id = data["selected_context"]["snapshot_id"]
            if role == "planner":
                action = {
                    "kind": "submit_plan",
                    "payload": {
                        "selected_agents": ["architecture_security"],
                        "priority_files": ["auth_routes.py"],
                        "priority_symbols": [],
                        "risk_areas": ["SQL injection"],
                        "review_tasks": [
                            {
                                "task_id": "t-sec",
                                "agent_id": "architecture_security",
                                "files": ["auth_routes.py"],
                                "focus": "Check SQL queries",
                            }
                        ],
                        "review_strategy": "Targeted baseline smoke test",
                        "coverage_expectations": ["auth_routes.py"],
                    },
                }
            elif role == "architecture_security":
                pending = next((p for p in evidence if p.get("next_offset") is not None), None)
                if not evidence:
                    action = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "auth_routes.py"}}
                elif pending is not None:
                    action = {
                        "kind": "call_tool",
                        "tool": "read_evidence",
                        "arguments": {"evidence_ref": pending["evidence_ref"], "offset": pending["next_offset"]},
                        "inspected_evidence": [p["evidence_ref"] for p in evidence],
                    }
                else:
                    action = {
                        "kind": "submit_candidates",
                        "inspected_evidence": [p["evidence_ref"] for p in evidence],
                        "payload": {
                            "task_id": "t-sec",
                            "agent_id": "architecture_security",
                            "candidates": [
                                {
                                    "category": "architecture_security",
                                    "title": "SQL injection in find_user",
                                    "description": "Formats username directly into SQL query",
                                    "impact": "Allows SQL injection",
                                    "confidence": 0.9,
                                    "location": {
                                        "snapshot_id": snapshot_id,
                                        "file_path": "auth_routes.py",
                                        "start_line": 14,
                                        "end_line": 15,
                                    },
                                    "evidence_refs": [evidence[0]["evidence_ref"]],
                                }
                            ],
                            "coverage": {},
                            "stop_reason": "evidence_complete",
                        },
                    }
            elif data["phase"] == "verification":
                pending = next((p for p in evidence if p.get("next_offset") is not None), None)
                if not evidence:
                    action = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "auth_routes.py"}}
                elif pending is not None:
                    action = {
                        "kind": "call_tool",
                        "tool": "read_evidence",
                        "arguments": {"evidence_ref": pending["evidence_ref"], "offset": pending["next_offset"]},
                        "inspected_evidence": [p["evidence_ref"] for p in evidence],
                    }
                else:
                    ref = evidence[0]["evidence_ref"]
                    action = {
                        "kind": "submit_verification",
                        "inspected_evidence": [ref],
                        "payload": {
                            "decisions": [
                                {
                                    "finding_id": fid,
                                    "verdict": "uncertain",
                                    "confidence": 0.5,
                                    "rationale": "Candidate remains unverified under independent check.",
                                    "evidence_refs": [ref],
                                }
                                for fid in data["candidates"]
                            ]
                        },
                    }
            else:
                action = {"kind": "submit_synthesis", "payload": {"summary": "Seeded smoke run", "limitations": []}}
            return LLMResponse(
                finish_reason="stop",
                content=json.dumps(action),
                provider="scripted",
                model=request.model,
                latency_ms=0,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

    summary = asyncio.run(
        run_seeded_scan(
            DEFAULT_REPO,
            DEFAULT_MANIFEST,
            runtime_dir=tmp_path / "runtime",
            provider=SeededScriptedProvider(),
            models={tier: tier.value for tier in ModelTier},
        )
    )
    assert summary["job_status"] == "completed"
    assert summary["found_count"] == 1
    assert summary["found"][0]["id"] == "SEED-05"
    assert summary["found"][0]["found_by"] == ["architecture_security"]


def test_run_seeded_scan_reports_missing_provider_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.run_seeded_scan.load_dotenv", lambda *args, **kwargs: False)
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "DEVWATCH_MODEL", "DEVWATCH_MODEL_MEDIUM"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEVWATCH_MODEL", "gpt-4o-mini")
    with pytest.raises(RuntimeError, match="No configured LLM provider credentials"):
        asyncio.run(run_seeded_scan(DEFAULT_REPO, DEFAULT_MANIFEST, runtime_dir=tmp_path / "runtime"))
