"""Deliberately narrow M11 fixture: only recognizes literal empty-list indexing.

This is not a model and must never be used for live accuracy measurements.
"""
import json

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.contracts import SPECIALISTS


class EvaluationProvider:
    def __init__(self, public, *, silent=False):
        assert set(public) == {"files", "contract"}
        self.public, self.silent = public, silent

    async def generate_completion(self, request):
        state = json.loads(request.prompt)
        task, private, context = state["task"], state["private_state"], state["selected_context"]
        role, phase = task["agent_id"], state["phase"]
        files = sorted(self.public["files"])
        if role == "planner":
            roles = sorted(role.value for role in SPECIALISTS)
            action = {"kind": "submit_plan", "payload": {"selected_agents": roles,
                "priority_files": files, "priority_symbols": [], "risk_areas": [],
                "review_tasks": [{"task_id": role, "agent_id": role, "files": files,
                                  "focus": self.public["contract"]} for role in roles],
                "review_strategy": "Scripted harness coverage", "coverage_expectations": files}}
        elif role != "synthesizer_verifier":
            if not private["evidence_refs"]:
                action = {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": files[0]}}
            else:
                candidates = []
                delivered = " ".join(page["excerpt"] for page in context["evidence"])
                if role == "bug_reliability" and "items[0]" in delivered and "if items" not in delivered and not self.silent:
                    candidates = [{"category": "bug", "title": "Empty input raises IndexError",
                        "description": "Empty input indexes element zero without a guard", "impact": "The caller crashes",
                        "confidence": .9, "location": {"snapshot_id": context["snapshot_id"], "file_path": files[0],
                        "start_line": 2, "end_line": 2}, "evidence_refs": private["evidence_refs"]}]
                action = {"kind": "submit_candidates", "payload": {"task_id": task["task_id"], "agent_id": role,
                    "candidates": candidates, "coverage": {}, "stop_reason": "evidence_complete"}}
        elif phase == "verification":
            if state["candidates"] and not private["evidence_refs"]:
                location = next(iter(state["candidates"].values()))["location"]
                action = {"kind": "call_tool", "tool": "read_source", "arguments": {
                    "file_path": location["file_path"], "start_line": location["start_line"], "end_line": location["end_line"]}}
            else:
                action = {"kind": "submit_verification", "payload": {"decisions": [{"finding_id": identity,
                    "verdict": "confirmed", "confidence": .9, "rationale": "Literal index zero is unguarded for empty input",
                    "evidence_refs": private["evidence_refs"]} for identity in state["candidates"]]}}
        else:
            action = {"kind": "submit_synthesis", "payload": {"summary": "Scripted evaluator integration check", "limitations": []}}
        action["inspected_evidence"] = [page["evidence_ref"] for page in context["evidence"]]
        return LLMResponse(content=json.dumps(action), provider="scripted-evaluation", model=request.model,
            latency_ms=0, finish_reason="stop", usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
