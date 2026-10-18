"""Milestone 11: independent-label evaluation of real specialist/full workflows."""

import math
import json
import sqlite3
import time
from contextlib import closing
from hashlib import sha256
from pathlib import Path


CORPUS_VERSION = "agent-evaluation-v1"


def load_corpus():
    """Six independently authored families, each with a repaired negative control.

    Public contracts specify intended behavior in both variants. Gold explanations,
    facets, severity and target roles are evaluation-only. No repository code is
    executed by this evaluator; tools retain their normal permission boundaries.
    """
    families = [
        ("empty", "python", "bug_reliability", "subject.py",
         "Return the first item, or None for empty input.",
         "def first(items):\n    return items[0]\n",
         "def first(items):\n    return items[0] if items else None\n", 2, 2,
         [["empty", "zero"], ["index", "raises", "crash"]], "medium", "defect",
         "Empty input unconditionally indexes element zero and raises IndexError."),
        ("mutation", "python", "logic_correctness", "subject.py",
         "Return sorted values without modifying the caller's input.",
         "def ordered(items):\n    items.sort()\n    return items\n",
         "def ordered(items):\n    return sorted(items)\n", 2, 2,
         [["mutat", "modif", "in-place", "in place"], ["sort", "input"]], "medium", "defect",
         "list.sort changes caller-owned input rather than returning an independent sorted result."),
        ("assertion", "python", "quality_testability", "test_subject.py",
         "Tests must fail if add(2, 3) returns an incorrect result. add is a normal integer sum.",
         "def test_add():\n    from subject import add\n    add(2, 3)\n",
         "def test_add():\n    from subject import add\n    assert add(2, 3) == 5\n", 3, 3,
         [["assert", "check", "verif"], ["test", "result"]], "low", "advisory",
         "The test invokes add without asserting its result, so a wrong returned sum passes."),
        ("query", "python", "architecture_security", "subject.py",
         "Look up a user by an untrusted name. Keep SQL data separate from query syntax.",
         "def find_user(db, name):\n    return db.execute(\"SELECT id FROM users WHERE name = '\" + name + \"'\").fetchone()\n",
         "def find_user(db, name):\n    return db.execute('SELECT id FROM users WHERE name = ?', (name,)).fetchone()\n", 2, 2,
         [["sql", "query"], ["inject", "concatenat", "untrusted", "parameter"]], "high", "defect",
         "Untrusted name is concatenated into SQL, allowing a quote to change the query predicate."),
        ("membership", "python", "performance_scalability", "subject.py",
         "Find unique integers in encounter order. Input can contain millions of distinct integers. Report unmeasured complexity as an advisory.",
         "def unique(items):\n    result = []\n    for value in items:\n        if value not in result:\n            result.append(value)\n    return result\n",
         "def unique(items):\n    result, seen = [], set()\n    for value in items:\n        if value not in seen:\n            seen.add(value)\n            result.append(value)\n    return result\n", 4, 4,
         [["quadratic", "o(n^2)", "o(n²)", "o(n2)", "linear scan"], ["list", "membership", "result"]], "medium", "advisory",
         "Each list membership scan grows with result length, causing quadratic comparisons on distinct inputs; no wall-clock speed claim is labelled."),
        ("offset", "javascript", "logic_correctness", "subject.js",
         "Convert one-based page numbers into zero-based offsets for pages of size ten.",
         "function offset(page) {\n  return page * 10;\n}\nmodule.exports = {offset};\n",
         "function offset(page) {\n  return (page - 1) * 10;\n}\nmodule.exports = {offset};\n", 2, 2,
         [["page", "offset"], ["one", "first", "10", "off-by-one", "off by one"]], "medium", "defect",
         "Page one incorrectly starts at offset ten, skipping the first page."),
    ]
    cases = []
    for family, language, specialist, path, contract, broken, repaired, start, end, facets, severity, kind, explanation in families:
        for defective, source in ((True, broken), (False, repaired)):
            files = {path: source}
            if family == "assertion":
                files["subject.py"] = "def add(a, b):\n    return a + b\n"
            cases.append({"case_id": family + ("-defect" if defective else "-clean"), "family": family,
                "language": language, "specialist": specialist, "files": files, "contract": contract,
                "gold": [{"defect_id": family, "file_path": path, "start_line": start, "end_line": end,
                          "facets": facets, "severity": severity, "kind": kind, "explanation": explanation}] if defective else []})
    return cases


def review_input(case):
    """An allowlist, never removal of a few known gold keys."""
    return {"files": dict(case["files"]), "contract": case["contract"]}


def _source_backed(finding, records):
    location = finding["location"]
    refs = finding.get("evidence_refs", [])
    if not refs or any(ref not in records or records[ref].get("snapshot_id") != location["snapshot_id"] for ref in refs):
        return False
    return any(record.get("tool") == "read_source" and record.get("file_path") == location["file_path"]
               and record.get("start_line", 0) <= location["start_line"]
               and record.get("end_line", 0) >= location["end_line"] for record in (records[ref] for ref in refs))


def score_findings(expected, findings, records, *, judgments=None):
    """Conservative automated screening, with explicit human semantic adjudication.

    Automatic matches need all gold text facets, an overlapping source location
    and valid snapshot evidence. Facets are a screening heuristic, not proof of
    causal correctness. Human judgments use zero-based finding indexes and can
    override semantics, never broken provenance/location. Maximum bipartite
    matching prevents duplicate claims or ordering from inflating recall.
    """
    judgments = judgments or {}
    known = {defect["defect_id"] for defect in expected}
    if set(judgments) - {str(i) for i in range(len(findings))}:
        raise ValueError("judgment references an unknown finding")
    if any(set(j) != {"defect_id", "evidence_correct"} or type(j.get("evidence_correct")) is not bool for j in judgments.values()):
        raise ValueError("finding judgments require defect_id and boolean evidence_correct")
    if any(j.get("defect_id") is not None and j["defect_id"] not in known for j in judgments.values()):
        raise ValueError("judgment references an unknown defect")
    source = [_source_backed(f, records) for f in findings]
    edges, localized = [], []
    for i, finding in enumerate(findings):
        location = finding["location"]
        text = " ".join(finding.get(key, "") for key in ("title", "description", "impact", "remediation")).lower()
        place = [d for d, defect in enumerate(expected) if location["file_path"] == defect["file_path"]
                 and location["start_line"] <= defect["end_line"] and location["end_line"] >= defect["start_line"]]
        localized.append(bool(place))
        judgment = judgments.get(str(i))
        edges.append([d for d in place if source[i] and (
            (judgment.get("defect_id") == expected[d]["defect_id"] and judgment.get("evidence_correct") is True)
            if judgment is not None else all(any(term.lower() in text for term in facet) for facet in expected[d]["facets"]))])
    assigned = {}
    def match(index, visited):
        for defect in edges[index]:
            if defect in visited:
                continue
            visited.add(defect)
            if defect not in assigned or match(assigned[defect], visited):
                assigned[defect] = index
                return True
        return False
    for i in range(len(findings)):
        match(i, set())
    tp, fp, fn = len(assigned), len(findings) - len(assigned), len(expected) - len(assigned)
    manual = [j["evidence_correct"] for j in judgments.values() if type(j.get("evidence_correct")) is bool]
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn,
        "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
        "duplicate_findings": sum(bool(edge) for edge in edges) - tp,
        "source_evidence_correctness": sum(source) / len(source) if source else None,
        "file_line_localization": sum(localized) / len(localized) if localized else None,
        "semantic_evidence_correctness": sum(manual) / len(manual) if manual else None,
        "semantic_judgments": len(manual), "severity_accuracy": None,
        "matches": [{"defect_id": expected[d]["defect_id"], "finding_index": i} for d, i in sorted(assigned.items())],
        "missed_defects": [d["defect_id"] for i, d in enumerate(expected) if i not in assigned],
        "matching_method": "human-adjudicated" if len(judgments) == len(findings) and findings else "facet-location-evidence-screen"}


def estimate_cost(usage, rates):
    if not usage or any(model not in rates for model in usage):
        return None
    total = 0.
    for model, tokens in usage.items():
        price = rates[model]
        for key in ("input_per_million", "output_per_million"):
            if not math.isfinite(price[key]) or price[key] < 0:
                raise ValueError("rates must be finite and nonnegative")
        total += (tokens["prompt_tokens"] * price["input_per_million"] +
                  tokens["completion_tokens"] * price["output_per_million"]) / 1_000_000
    return total


class MeasuredProvider:
    """Local usage meter; optional conservative supplied-rate spending guard.

    Reserve UTF-8 prompt bytes plus framing allowance as input tokens and the
    requested output ceiling. Keep unknown completions charged. This is an
    estimate using supplied prices, not a provider billing guarantee.
    """
    def __init__(self, provider, *, rates=None, max_cost_usd=None):
        if max_cost_usd is not None and (not math.isfinite(max_cost_usd) or max_cost_usd <= 0):
            raise ValueError("cost cap must be positive and finite")
        self.provider, self.rates, self.max_cost_usd = provider, rates or {}, max_cost_usd
        self.usage, self.unknown_calls, self.charged_usd = {}, 0, 0.

    async def generate_completion(self, request):
        reserve = 0.
        if self.max_cost_usd is not None:
            if request.model not in self.rates or not request.max_tokens:
                raise RuntimeError("cost guard requires model rates and an output bound")
            reserve = estimate_cost({request.model: {
                "prompt_tokens": len(request.prompt.encode()) + len(request.system_prompt.encode()) + 1024,
                "completion_tokens": request.max_tokens}}, self.rates)
            if self.charged_usd + reserve > self.max_cost_usd:
                raise RuntimeError("evaluation cost cap reached before dispatch")
            self.charged_usd += reserve
        try:
            response = await self.provider.generate_completion(request)
        except BaseException:
            self.unknown_calls += 1
            raise
        actual = {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens}
        if min(*actual.values(), response.usage.total_tokens) < 0 or max(sum(actual.values()), response.usage.total_tokens) == 0:
            self.unknown_calls += 1
            return response
        # Gemini's compatibility endpoint can include thinking only in total_tokens.
        # Price unallocated tokens as output (the more expensive selected rate),
        # rather than silently dropping them or billing them as cheap input.
        actual["completion_tokens"] += max(0, response.usage.total_tokens - sum(actual.values()))
        usage = self.usage.setdefault(request.model, {"prompt_tokens": 0, "completion_tokens": 0})
        for key, value in actual.items():
            usage[key] += value
        if self.max_cost_usd is not None:
            self.charged_usd += estimate_cost({request.model: actual}, self.rates) - reserve
        return response


async def run_case(case, runtime_root, *, mode, provider, live=False, models=None, judgments=None):
    """Run real isolated specialist subgraph or unchanged seven-agent full graph.

    Individual mode intentionally excludes planning/verification/synthesis and
    scores raw specialist claims. Full mode scores accepted report groups and
    separately records pre-verification candidates. No gold enters either path.
    """
    from devwatch.review.budgets import BudgetManager
    from devwatch.review.contracts import AgentId, EvidenceProgress, ModelTier, ReviewTask
    from devwatch.review.jobs import DurableJobManager, EventStore, JobStore
    from devwatch.review.repository import RepositoryContext
    from devwatch.review.stores import ArtifactStore, RepoCache, StoreLayout
    from devwatch.review.workflow import CanonicalReviewExecutor, _ReviewSession

    if mode not in {"specialist", "full"}:
        raise ValueError("mode must be specialist or full")
    public = review_input(case)
    layout = StoreLayout(Path(runtime_root))
    if layout.jobs.exists():
        raise ValueError("evaluation requires a fresh runtime directory")
    artifacts = ArtifactStore(layout.artifacts)
    # Full Planner discovers the same public specification as every other file.
    files = {**public["files"], "REVIEW_CONTRACT.md": public["contract"] + "\n"}
    snapshot = artifacts.capture(owner="evaluation", files=files)
    jobs, events = JobStore(layout.jobs), EventStore(layout.events)
    cache = RepoCache(layout.repo_cache)
    repository = RepositoryContext(artifacts, cache, snapshot.snapshot_id, owner="evaluation")
    meter = provider if isinstance(provider, MeasuredProvider) else MeasuredProvider(provider)
    usage_before = json.loads(json.dumps(meter.usage))
    unknown_before = meter.unknown_calls
    executor = CanonicalReviewExecutor(layout, artifacts, cache, jobs, events, meter,
        models=models or {tier: tier.value + "-scripted" for tier in ModelTier})

    async def individual(job):
        budget = BudgetManager(job.limits, job.ledger.model_copy(deep=True))
        budget.begin_execution()
        session = _ReviewSession(executor, job, repository, budget, sorted(public["files"]))
        task = ReviewTask(task_id="individual", agent_id=AgentId(case["specialist"]),
                          files=sorted(public["files"]), focus=public["contract"])
        result = await session.run_task_safely(task)
        return {"json": result.model_dump_json()}

    started = time.monotonic()
    manager = DurableJobManager(jobs, events, executor if mode == "full" else individual)
    try:
        job = await manager.submit(owner="evaluation", request={"snapshot_id": snapshot.snapshot_id},
                                   idempotency_key="evaluation")
        finished = await manager.wait(job.job_id, owner="evaluation")
    finally:
        await manager.close()
    latency = time.monotonic() - started
    thread_id = sha256(("evaluation\0" + job.job_id).encode()).hexdigest()
    with closing(sqlite3.connect(layout.checkpoints)) as db:
        states = [json.loads(row[0]) for row in db.execute("SELECT state FROM agent_progress WHERE thread_id=?", (thread_id,))]
    candidates, records, inspected, roles = [], {}, set(), set()
    invalid_evidence = 0
    for state in states:
        role = state["task"]["agent_id"]
        roles.add(role)
        private = state["private_state"]
        if role not in {"planner", "synthesizer_verifier"}:
            candidates.extend(private.get("local_findings", []))
        for ref in private.get("evidence_refs", []):
            if ref not in records:
                try:
                    records[ref] = repository.evidence(ref)
                except (ValueError, OSError):
                    invalid_evidence += 1
            receipt = private.get("evidence_progress", {}).get(ref)
            if (receipt and EvidenceProgress.model_validate(receipt).fully_inspected()
                    and records.get(ref, {}).get("tool") == "read_source"):
                inspected.add(records[ref]["file_path"])
    report = json.loads(finished.result["json"]) if finished.result and "json" in finished.result else {}
    findings = (sum((report.get(key, []) for key in ("confirmed_defects", "uncertain_high_impact_candidates", "advisories")), [])
                if mode == "full" else report.get("candidates", []))
    score = score_findings(case["gold"], findings, records, judgments=judgments)
    candidate_score = score_findings(case["gold"], candidates, records)
    timeline, cursor = [], 0
    while page := events.replay(job.job_id, after=cursor):
        timeline.extend(page)
        cursor = page[-1].sequence
    calls = [event for event in timeline if event.kind == "tool_result"]
    successes = sum(event.payload.outcome == "succeeded" for event in calls)
    seen, repeated = set(), 0
    for event in calls:
        payload = event.payload
        if payload.outcome == "succeeded" and payload.tool != "read_evidence":
            identity = (payload.agent_id, payload.task_id, payload.tool, payload.evidence_ref)
            repeated += identity in seen
            seen.add(identity)
    usage = {model: {key: value - usage_before.get(model, {}).get(key, 0) for key, value in tokens.items()}
             for model, tokens in meter.usage.items()}
    categories = set()
    if any(event.payload.outcome == "failed" for event in calls) or invalid_evidence:
        categories.add("tool_harness" if not invalid_evidence else "evidence_retrieval")
    missing = bool(score["false_negative"])
    provider_errors = sorted({e.payload.error_code for e in timeline if e.kind == "model_call_completed" and e.payload.error_code})
    if provider_errors:
        categories.add("tool_harness")
    if missing and not provider_errors:
        if mode == "full" and case["specialist"] not in roles:
            categories.add("orchestration")
        elif candidate_score["true_positive"] > score["true_positive"]:
            categories.add("verification")
        elif not set(public["files"]).issubset(inspected):
            categories.add("evidence_retrieval")
        else:
            categories.add("model_reasoning")
    if score["false_positive"]:
        categories.add("model_reasoning")
    if report.get("coverage", {}).get("failed", {}).get("__final") or any(
            event.payload.stop_reason == "final_consistency_failure" for event in timeline):
        categories.add("finalization")
    if finished.status != "completed" and not categories:
        categories.add("tool_harness")
    metrics = {"latency_seconds": latency, "tool_calls": len(calls),
        "successful_tool_fraction": successes / len(calls) if calls else None,
        "tool_selection_quality": None, "unnecessary_tool_calls": None,
        "repeated_identical_evidence_calls": repeated,
        "inspected_source_fraction": len(inspected.intersection(public["files"])) / len(public["files"]),
        "prompt_tokens": sum(u["prompt_tokens"] for u in usage.values()),
        "completion_tokens": sum(u["completion_tokens"] for u in usage.values()),
        "ledger_total_tokens": finished.ledger.total_tokens, "model_calls": sum(e.kind == "model_call_started" for e in timeline),
        "unknown_provider_calls": meter.unknown_calls - unknown_before,
        "cost_guard_charged_usd": meter.charged_usd if live else None,
        "approximate_cost_usd": estimate_cost(usage, meter.rates) if live and meter.unknown_calls == unknown_before else None,
        "usage_by_model": usage}
    return {"case_id": case["case_id"], "specialist": case["specialist"], "mode": mode,
        "status": finished.status, "score": score, "candidate_score": candidate_score, "metrics": metrics,
        "models": {tier.value: name for tier, name in executor.models.items()},
        # Partial model investigations and schema failures are quality failures,
        # not grounds for excluding a difficult case. Only external model-call
        # failure or failed job execution makes this run unavailable to score.
        "evaluation_eligible": finished.status == "completed" and not provider_errors,
        "provider_error_codes": provider_errors,
        "agents_executed": sorted(roles), "failure_categories": sorted(categories),
        "failure_attribution": "trace-based triage; root cause requires inspection",
        "human_reviewed": judgments is not None and len(judgments) == len(findings),
        "live_model_accuracy": None,
        "tool_observations": [{"operation_id": e.payload.operation_id, "agent_id": e.payload.agent_id,
            "task_id": e.payload.task_id, "tool": e.payload.tool, "outcome": e.payload.outcome,
            "evidence_ref": e.payload.evidence_ref} for e in calls],
        "findings": findings, "candidates": candidates, "gold": case["gold"], "evidence": records,
        "coverage": report.get("coverage", {}), "snapshot_id": snapshot.snapshot_id}


def summarize(rows, *, live):
    groups = {}
    keys = sorted({"full" if row["mode"] == "full" else "specialist:" + row["specialist"] for row in rows})
    for key in keys:
        all_runs = [row for row in rows if ("full" if row["mode"] == "full" else "specialist:" + row["specialist"]) == key]
        subset = [row for row in all_runs if row.get("evaluation_eligible", True)]
        counts = {name: sum(row["score"][name] for row in subset) for name in ("true_positive", "false_positive", "false_negative")}
        tp, fp, fn = (counts[name] for name in ("true_positive", "false_positive", "false_negative"))
        groups[key] = {**counts, "runs": len(all_runs), "eligible_runs": len(subset), "excluded_runs": len(all_runs) - len(subset),
                       "precision": tp / (tp + fp) if tp + fp else None,
                       "recall": tp / (tp + fn) if tp + fn else None}
    return {"version": CORPUS_VERSION, "mode": "live-model" if live else "scripted-harness-validation",
        "corpus_sha256": sha256(json.dumps(load_corpus(), sort_keys=True).encode()).hexdigest(),
        "groups": groups, "live_model_screening": groups if live else None,
        "live_model_accuracy": groups if live and rows and all(row.get("human_reviewed") and row.get("evaluation_eligible", True) for row in rows) else None,
        "limitations": ["Small transparent corpus; paired controls are not independent statistical samples.",
            "Text facets screen semantic matches; human adjudication is required for causal accuracy.",
            "Severity is not emitted by the production finding contract and cannot be measured.",
            "Tool success/repeated evidence and inspected source are proxies, not causal tool-quality judgments."]}


def adjudicate_row(row, judgments):
    """Rescore saved observations without making a provider call.

    Tool quality/necessity require explicit judgments on actual operation IDs.
    Partial annotations report denominators and never masquerade as full review.
    """
    result = {**row, "metrics": dict(row["metrics"])}
    result["evaluation_eligible"] = row["status"] == "completed" and not row.get("provider_error_codes", [])
    result["score"] = score_findings(row["gold"], row["findings"], row["evidence"],
                                     judgments=judgments.get("findings", {}))
    result["human_reviewed"] = ("findings" in judgments and
                                len(judgments["findings"]) == len(row["findings"]))
    tools = judgments.get("tools", {})
    observed = {tool["operation_id"] for tool in row["tool_observations"]}
    if set(tools) - observed:
        raise ValueError("judgment references an unobserved tool operation")
    if any(type(j.get(key)) is not bool for j in tools.values() for key in ("appropriate", "necessary")):
        raise ValueError("tool judgments require boolean appropriate and necessary")
    result["metrics"].update(tool_judgments=len(tools),
        tool_selection_quality=sum(j["appropriate"] for j in tools.values()) / len(tools) if tools else None,
        unnecessary_tool_calls=sum(not j["necessary"] for j in tools.values()) if tools else None)
    return result
