"""Canonical review quality harness with independent labels and real tool evidence.

Offline mode exercises contracts, command execution, verification and acceptance.
Its deterministic fixture provider is test infrastructure, never a product review
engine or a claim about live-model reasoning. --live uses the configured provider;
it is explicit, invokes paid model calls and reports separate measurements.
"""
import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.contracts import ModelTier
from devwatch.review.jobs import DurableJobManager, EventStore, JobStore
from devwatch.review.stores import ArtifactStore, RepoCache, StoreLayout
from devwatch.review.tool_runtime import TrustedCommand
from devwatch.review.workflow import CanonicalReviewExecutor
from devwatch.review.repository import RepositoryContext
from scripts.evaluate_agents import score_findings


class ContractProbeProvider:
    def __init__(self, public_case, *, suppress_candidates=False):
        if "expected_defect" in public_case:
            raise ValueError("Review provider cannot receive gold labels")
        self.case, self.suppress = public_case, suppress_candidates
        self.evidence_pages = {}

    async def generate_completion(self, request):
        state = json.loads(request.prompt)
        task, private, context = state["task"], state["private_state"], state["selected_context"]
        role, phase = task["agent_id"], state["phase"]
        source = self.case["subject"]
        # The offline model fixture obeys the same paging protocol as a live
        # reviewer. Caches are role-local; a verifier must receive its own pages.
        pages = self.evidence_pages.setdefault(role, {})
        for page in context["evidence"]:
            pages.setdefault(page["evidence_ref"], {})[page["offset"]] = page
        records, pending = [], []
        for ref, segments in pages.items():
            cursor, parts = 0, []
            while cursor in segments:
                page = segments[cursor]
                parts.append(page["excerpt"])
                cursor = page["end_offset"]
                if page["next_offset"] is None:
                    records.append({"evidence_ref": ref, **json.loads("".join(parts))})
                    break
            else:
                pending.append((ref, cursor))
        if pending:
            ref, offset = pending[0]
            action = {"kind": "call_tool", "tool": "read_evidence", "arguments": {"evidence_ref": ref, "offset": offset}}
        elif role == "planner":
            action = {"kind": "submit_plan", "payload": {
                "selected_agents": ["bug_reliability"], "priority_files": [source], "priority_symbols": ["f"],
                "risk_areas": ["Executable public behavior contract"], "review_tasks": [{"task_id": "contract-probe", "agent_id": "bug_reliability",
                    "files": sorted(self.case["files"]), "focus": self.case["contract"]}],
                "review_strategy": "Inspect immutable source and run the approved independent contract probe",
                "coverage_expectations": sorted(self.case["files"])}}
        elif role == "bug_reliability":
            by_tool = {record["tool"]: record for record in records}
            sources = {record['file_path']: record for record in records if record['tool'] == 'read_source'}
            unread_sources = sorted(set(task['files']) - sources.keys())
            if "parse_ast" not in by_tool:
                action = {"kind": "call_tool", "tool": "parse_ast", "arguments": {"file_path": source}}
            elif "read_source" not in by_tool:
                action = {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": source}}
            elif unread_sources:
                action = {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": unread_sources[0]}}
            elif "run_tests" not in by_tool:
                action = {"kind": "call_tool", "tool": "run_tests", "arguments": {"command_id": "contract-probe"}}
            else:
                measurement = by_tool["run_tests"]["data"]
                output = measurement["stderr"]
                reproduced = (not measurement["timed_out"] and not measurement["truncated"] and measurement["exit_code"] != 0
                    and any(marker in output for marker in ("AssertionError", "IndexError", "ERR_ASSERTION")))
                candidates = []
                if reproduced and not self.suppress:
                    candidates = [{"category": "bug", "title": "Executable behavior contract violated",
                        "description": self.case["contract"], "impact": "A supported input violates its explicit result or mutation contract.",
                        "confidence": .95, "location": {"snapshot_id": context["snapshot_id"], "file_path": source, "start_line": 2, "end_line": 2},
                        "evidence_refs": [sources[source]["evidence_ref"], by_tool["run_tests"]["evidence_ref"]]}]
                action = {"kind": "submit_candidates", "payload": {"task_id": task["task_id"], "agent_id": role,
                    "candidates": candidates, "coverage": {}, "stop_reason": "evidence_complete"}}
        elif phase == "verification":
            needed = sorted({ref for candidate in state["candidates"].values() for ref in candidate["evidence_refs"]})
            unread = [ref for ref in needed if ref not in private["evidence_refs"]]
            if unread:
                action = {"kind": "call_tool", "tool": "read_evidence", "arguments": {"evidence_ref": unread[0]}}
            else:
                commands = [record["data"] for record in records if record["tool"] == "run_tests"]
                confirmed = any(data["exit_code"] != 0 and not data["timed_out"] and not data["truncated"] for data in commands)
                decisions = [{"finding_id": identity, "verdict": "confirmed" if confirmed else "rejected", "confidence": .95,
                    "rationale": "Independent executable probe reproduces the documented contract violation against immutable source." if confirmed else "No reproducible contract violation.",
                    "evidence_refs": candidate["evidence_refs"],
                    # Programmed protocol fixture, not a live semantic judgment.
                    "causal_review": {"candidate_digest": state['candidate_digests'][identity],
                        "causal_basis": "The independent executable contract probe fails against the inspected immutable source, rather than producing the documented result/state.",
                        "assessments": [{"field": field, "status": "supported",
                            "explanation": "Immutable source and the trusted contract-probe failure establish this field.",
                            "evidence_refs": candidate['evidence_refs']}
                            for field in ('title','description','impact','remediation')]} if confirmed else None}
                    for identity, candidate in state["candidates"].items()]
                action = {"kind": "submit_verification", "payload": {"decisions": decisions}}
        else:
            verified = state["verified"]
            decisions = {decision["finding_id"]: decision for decision in verified["decisions"]}
            findings = [{**candidate, "finding_id": identity, "kind": "defect", "confidence": decisions[identity]["confidence"],
                "verification_rationale": decisions[identity]["rationale"]} for identity, candidate in state["candidates"].items()
                if decisions[identity]["verdict"] == "confirmed"]
            action = {"kind": "submit_synthesis", "payload": {**verified, "report_draft": {"snapshot_id": context["snapshot_id"],
                "summary": "Offline executable-contract integration result", "confirmed_defects": findings, "coverage": {}}, "coverage_summary": {}}}
        # Explicit synthetic accounting: these are not billed provider tokens.
        action["inspected_evidence"] = [page["evidence_ref"] for page in context["evidence"]]
        return LLMResponse(finish_reason="stop", content=json.dumps(action), provider="offline-contract-fixture", model=request.model,
            latency_ms=0, usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


async def evaluate(cases, runtime_root, *, provider_factory=ContractProbeProvider, live=False):
    rows, true_positive, false_positive, false_negative, failed_jobs = [], 0, 0, 0, 0
    candidate_tp = candidate_fp = candidate_fn = published_positives = 0
    for index, case in enumerate(cases):
        public = {key: value for key, value in case.items() if key not in {"expected_defect", "case_id"}}
        layout = StoreLayout(Path(runtime_root) / f"case-{index}")
        artifacts = ArtifactStore(layout.artifacts)
        snapshot = artifacts.capture(owner="evaluation", files=case["files"])
        jobs, events = JobStore(layout.jobs), EventStore(layout.events)
        if case["language"] == "python":
            executable, arguments = sys.executable, ("-I", case["probe"])
        else:
            executable, arguments = shutil.which("node"), (case["probe"],)
            if executable is None:
                raise RuntimeError("JavaScript evaluation requires an installed Node executable")
        command = TrustedCommand(command_id="contract-probe", tool="run_tests", argv=(executable, *arguments),
            files=tuple(sorted(case["files"])), timeout_seconds=10)
        if live:
            from devwatch.review.service import ServiceSettings
            from devwatch.providers.openai_adapter import OpenAIProviderAdapter
            import os
            settings = ServiceSettings.from_env()
            provider = OpenAIProviderAdapter(provider_name=os.getenv("DEVWATCH_PROVIDER", "openai"), request_delay=0)
            models = settings.models
        else:
            provider = provider_factory(public)
            models = {tier: tier.value + "-offline-fixture" for tier in ModelTier}
        executor = CanonicalReviewExecutor(layout, artifacts, RepoCache(layout.repo_cache), jobs, events, provider,
            models=models, trusted_commands=(command,))
        manager = DurableJobManager(jobs, events, executor)
        try:
            job = await manager.submit(owner="evaluation", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key=case["case_id"])
            finished = await manager.wait(job.job_id, owner="evaluation")
            if finished.status != "completed":
                failed_jobs += 1
                confirmed = 0
                coverage_failed = True
                findings, all_findings, records = [], [], {}
            else:
                report = json.loads(finished.result["json"])
                findings = report["confirmed_defects"]
                all_findings = findings + report['uncertain_high_impact_candidates'] + report['advisories']
                published_positives += len(findings) + len(report['advisories'])
                confirmed = len(findings)
                repository = RepositoryContext(artifacts, RepoCache(layout.repo_cache), snapshot.snapshot_id, owner="evaluation")
                records = {ref: repository.evidence(ref) for finding in all_findings for ref in finding["evidence_refs"]}
                coverage_failed = bool(report["coverage"]["failed"])
                failed_jobs += int(coverage_failed)
            expected = case["expected_defect"]
            # Version 2 labels describe a single executable contract at line 2.
            # Require that specific claim, location and immutable evidence; an
            # unrelated finding on a defective sample is a false positive/miss.
            gold = [{"defect_id": case["family"], "file_path": case["subject"], "start_line": 2,
                     "end_line": 2, "facets": [[case["contract"]]]}] if expected else []
            score = score_findings(gold, findings, records)
            candidate_score = score_findings(gold, all_findings, records)
            candidate_tp += candidate_score['true_positive']
            candidate_fp += candidate_score['false_positive']
            candidate_fn += candidate_score['false_negative']
            true_positive += score["true_positive"]
            false_negative += score["false_negative"]
            false_positive += score["false_positive"]
            rows.append({"case_id": case["case_id"], "expected_defect": expected, "confirmed": confirmed,
                "status": finished.status, "coverage_failed": coverage_failed, "score": score,
                "candidate_score": candidate_score})
        finally:
            await manager.close()
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.
    candidate_precision = candidate_tp / (candidate_tp + candidate_fp) if candidate_tp + candidate_fp else 0.
    candidate_recall = candidate_tp / (candidate_tp + candidate_fn) if candidate_tp + candidate_fn else 1.
    return {"version": "canonical-review-eval-v2", "mode": "live-model" if live else "offline-contract-integration",
        "cases": len(cases), "true_positive": true_positive, "false_positive": false_positive, "false_negative": false_negative,
        "confirmed_precision": precision, "confirmed_recall": recall, "failed_jobs": failed_jobs,
        "candidate_precision": candidate_precision, "candidate_recall": candidate_recall,
        "publication_policy_satisfied": published_positives == 0,
        "passes_candidate_gate": len(cases) >= 60 and candidate_precision >= .9 and candidate_recall >= .7 and failed_jobs == 0,
        "passes_quality_gate": len(cases) >= 60 and precision >= .9 and recall >= .7 and failed_jobs == 0,
        "live_model_accuracy": None,
        "live_model_screening": {"precision": precision, "recall": recall} if live else None,
        "matching_method": "contract-text-location-evidence-screen; human semantic adjudication required",
        "corpus_sha256": sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(), "results": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Explicitly use configured paid providers; never enabled by default")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    corpus = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/canonical-review-eval-v2.json").read_text())
    with tempfile.TemporaryDirectory(prefix="devwatch-evaluation-") as runtime:
        result = asyncio.run(evaluate(corpus["cases"], runtime, live=args.live))
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "results"}))
    raise SystemExit(0 if result["passes_quality_gate"] else 1)


if __name__ == "__main__":
    main()
