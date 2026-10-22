"""Evaluator regressions: a finding's existence must never imply correctness."""
import json

import pytest

from scripts import evaluate_agents as evaluation


def api(name):
    function = getattr(evaluation, name, None)
    assert callable(function), f"M11 evaluator needs {name}"
    return function


def gold():
    return {"defect_id": "empty-input", "file_path": "subject.py", "start_line": 2,
            "end_line": 2, "facets": [["empty", "zero"], ["index", "raises"]],
            "severity": "medium", "explanation": "Empty input indexes element zero."}


def finding(**changes):
    return {"title": "Empty input raises IndexError", "description": "An empty list is indexed",
            "impact": "Caller crashes", "location": {"snapshot_id": "snapshot", "file_path": "subject.py",
            "start_line": 2, "end_line": 2}, "evidence_refs": ["source"], **changes}


def evidence():
    return {"source": {"snapshot_id": "snapshot", "tool": "read_source", "file_path": "subject.py",
            "source_scope": ["subject.py"], "start_line": 1, "end_line": 2,
            "data": "def first(items):\n    return items[0]"}}


@pytest.mark.parametrize("change", [
    {"title": "Unused import", "description": "Remove dead code", "impact": "Style"},
    {"location": {"snapshot_id": "snapshot", "file_path": "other.py", "start_line": 2, "end_line": 2}},
    {"location": {"snapshot_id": "snapshot", "file_path": "subject.py", "start_line": 8, "end_line": 8}},
    {"evidence_refs": ["missing"]},
])
def test_unrelated_or_unsupported_finding_is_both_false_positive_and_miss(change):
    result = api("score_findings")([gold()], [finding(**change)], evidence())
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (0, 1, 1)


def test_duplicate_cannot_inflate_recall_and_is_a_false_positive():
    result = api("score_findings")([gold()], [finding(), finding()], evidence())
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (1, 1, 0)
    assert result["duplicate_findings"] == 1
    assert result["severity_accuracy"] is None
    assert result["semantic_evidence_correctness"] is None


def test_each_expected_defect_needs_its_own_match():
    second = {**gold(), "defect_id": "mutation", "facets": [["mutation"]]}
    result = api("score_findings")([gold(), second], [finding()], evidence())
    assert (result["true_positive"], result["false_negative"]) == (1, 1)


def test_clean_case_has_no_false_negatives_but_flags_findings():
    result = api("score_findings")([], [finding()], evidence())
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (0, 1, 0)


def test_forged_snapshot_or_unrelated_evidence_is_not_correct():
    for record in [{**evidence()["source"], "snapshot_id": "different"},
                   {**evidence()["source"], "file_path": "other.py"}]:
        result = api("score_findings")([gold()], [finding()], {"source": record})
        assert result["true_positive"] == 0
        assert result["source_evidence_correctness"] == 0


def test_gold_never_crosses_reviewer_boundary():
    case = api("load_corpus")()[0]
    public = api("review_input")(case)
    assert set(public) == {"files", "contract"}
    assert "gold" not in json.dumps(public)
    assert "defect_id" not in json.dumps(public)


def test_corpus_covers_all_specialists_and_contains_paired_clean_controls():
    cases = api("load_corpus")()
    assert len(cases) >= 12
    assert len({c["case_id"] for c in cases}) == len(cases)
    assert {c["language"] for c in cases} == {"python", "javascript"}
    assert {c["specialist"] for c in cases} == {"bug_reliability", "logic_correctness", "quality_testability",
                                              "architecture_security", "performance_scalability"}
    for family in {c["family"] for c in cases}:
        pair = [c for c in cases if c["family"] == family]
        assert len(pair) == 2
        assert sorted(bool(c["gold"]) for c in pair) == [False, True]
        assert pair[0]["contract"] == pair[1]["contract"]
        assert pair[0]["files"] != pair[1]["files"]
        for case in pair:
            for defect in case["gold"]:
                assert defect["end_line"] <= len(case["files"][defect["file_path"]].splitlines())


def test_source_metric_requires_every_reference_to_be_valid():
    result = api("score_findings")([gold()], [finding(evidence_refs=["source", "missing"])], evidence())
    assert result["true_positive"] == 0


def test_manual_adjudication_can_reject_keyword_only_match():
    result = api("score_findings")([gold()], [finding()], evidence(),
        judgments={"0": {"defect_id": None, "evidence_correct": False}})
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (0, 1, 1)
    assert result["semantic_evidence_correctness"] == 0


def test_matching_maximizes_distinct_defects_instead_of_greedy_assignment():
    broad = {**gold(), "defect_id": "broad", "facets": [["empty"]]}
    narrow = {**gold(), "defect_id": "narrow", "facets": [["indexerror"]]}
    result = api("score_findings")([broad, narrow], [finding(), finding(title="Empty boundary", description="empty", impact="crash")], evidence())
    assert result["true_positive"] == 2


def test_cost_unknown_without_rates_and_exact_with_explicit_rates():
    usage = {"model": {"prompt_tokens": 1000, "completion_tokens": 200}}
    assert api("estimate_cost")(usage, {}) is None
    assert api("estimate_cost")(usage, {"model": {"input_per_million": 2, "output_per_million": 8}}) == .0036


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["specialist", "full"])
async def test_runner_uses_real_runtime_and_scores_expected_defect(tmp_path, mode):
    from tests.evaluation_provider import EvaluationProvider
    case = api("load_corpus")()[0]
    result = await api("run_case")(case, tmp_path, mode=mode,
        provider=EvaluationProvider(api("review_input")(case)), live=False)
    assert result["score"]["true_positive"] == 1
    assert result["status"] == "completed"
    assert result["metrics"]["prompt_tokens"] > 0
    assert result["metrics"]["tool_calls"] >= 1
    assert result["metrics"]["inspected_source_fraction"] == 1
    assert result["metrics"]["approximate_cost_usd"] is None
    assert result["live_model_accuracy"] is None
    assert result["metrics"]["latency_seconds"] > 0
    roles = set(result["agents_executed"])
    assert "bug_reliability" in roles
    assert ("planner" in roles) == (mode == "full")
    assert ("synthesizer_verifier" in roles) == (mode == "full")


@pytest.mark.asyncio
async def test_silent_specialist_is_false_negative_not_success(tmp_path):
    from tests.evaluation_provider import EvaluationProvider
    case = api("load_corpus")()[0]
    result = await api("run_case")(case, tmp_path, mode="specialist",
        provider=EvaluationProvider(api("review_input")(case), silent=True), live=False)
    assert result["score"]["false_negative"] == 1
    assert result["failure_categories"] == ["model_reasoning"]


@pytest.mark.asyncio
async def test_scripted_evaluator_inspects_every_assigned_file_before_completion(tmp_path):
    from tests.evaluation_provider import EvaluationProvider
    case = next(case for case in api('load_corpus')() if len(case['files']) > 1)
    result = await api('run_case')(case, tmp_path, mode='full',
        provider=EvaluationProvider(api('review_input')(case)), live=False)
    assert result['metrics']['inspected_source_fraction'] == 1
    # This deliberately narrow reviewer still misses the assertion-family defect.
    assert result['failure_categories'] == ['model_reasoning']


@pytest.mark.asyncio
async def test_cost_guard_rejects_before_provider_call_and_keeps_unknown_charge():
    from devwatch.providers.base import LLMRequest
    class Provider:
        calls = 0
        async def generate_completion(self, request):
            self.calls += 1
            raise TimeoutError("unknown charge")
    provider = Provider()
    wrapped = api("MeasuredProvider")(provider,
        rates={"m": {"input_per_million": 1, "output_per_million": 1}}, max_cost_usd=.002)
    request = LLMRequest(model="m", prompt="hello", max_tokens=100)
    with pytest.raises(TimeoutError):
        await wrapped.generate_completion(request)
    with pytest.raises(RuntimeError, match="cost"):
        await wrapped.generate_completion(request)
    assert provider.calls == 1
    assert wrapped.unknown_calls == 1


@pytest.mark.asyncio
async def test_cost_meter_prices_unallocated_reasoning_tokens_as_output():
    from devwatch.providers.base import LLMRequest, LLMResponse, LLMUsage
    class Provider:
        async def generate_completion(self, request):
            return LLMResponse(content="ok", provider="fixture", model="m", latency_ms=0,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=115))
    wrapped = api("MeasuredProvider")(Provider(),
        rates={"m": {"input_per_million": 1, "output_per_million": 10}}, max_cost_usd=1)
    await wrapped.generate_completion(LLMRequest(model="m", prompt="hi", max_tokens=200))
    assert wrapped.usage["m"] == {"prompt_tokens": 10, "completion_tokens": 105}
    assert wrapped.charged_usd == pytest.approx(.00106)


@pytest.mark.asyncio
async def test_missing_usage_keeps_reservation_instead_of_claiming_free_call():
    from devwatch.providers.base import LLMRequest, LLMResponse
    class Provider:
        async def generate_completion(self, request):
            return LLMResponse(content="ok", provider="fixture", model="m", latency_ms=0)
    wrapped = api("MeasuredProvider")(Provider(),
        rates={"m": {"input_per_million": 1, "output_per_million": 10}}, max_cost_usd=1)
    await wrapped.generate_completion(LLMRequest(model="m", prompt="hi", max_tokens=200))
    assert wrapped.unknown_calls == 1
    assert wrapped.charged_usd > 0
    assert not wrapped.usage


def test_summary_keeps_offline_quality_separate_from_live_results():
    rows = [{"mode": "full", "specialist": "bug_reliability", "score": {
        "true_positive": 1, "false_positive": 1, "false_negative": 1}, "status": "completed"}]
    result = api("summarize")(rows, live=False)
    assert result["groups"]["full"]["precision"] == .5
    assert result["groups"]["full"]["recall"] == .5
    assert result["live_model_accuracy"] is None


def test_provider_blocked_runs_are_excluded_from_quality_estimates():
    rows = [{"mode": "specialist", "specialist": "bug_reliability", "score": {
        "true_positive": 0, "false_positive": 0, "false_negative": 1}, "status": "completed", "evaluation_eligible": False}]
    result = api("summarize")(rows, live=True)
    assert result["groups"]["specialist:bug_reliability"]["recall"] is None
    assert result["groups"]["specialist:bug_reliability"]["excluded_runs"] == 1


def test_incomplete_human_judgments_cannot_be_presented_as_adjudicated():
    with pytest.raises(ValueError, match="judgment"):
        api("score_findings")([gold()], [finding()], evidence(), judgments={"0": {"defect_id": "empty-input"}})


@pytest.mark.asyncio
async def test_provider_failure_is_harness_failure_not_model_reasoning(tmp_path):
    from devwatch.providers.exceptions import ProviderQuotaExhaustedError
    class UnavailableProvider:
        async def generate_completion(self, request):
            raise ProviderQuotaExhaustedError("No provider quota", provider="fixture")
    result = await api("run_case")(api("load_corpus")()[0], tmp_path, mode="specialist", provider=UnavailableProvider())
    assert result["evaluation_eligible"] is False
    assert result["failure_categories"] == ["tool_harness"]
    assert result["provider_error_codes"] == ["provider_quota"]


@pytest.mark.asyncio
async def test_partial_model_review_still_counts_toward_quality(tmp_path):
    from tests.evaluation_provider import EvaluationProvider
    class NarrativeStop(EvaluationProvider):
        async def generate_completion(self, request):
            response = await super().generate_completion(request)
            action = json.loads(response.content)
            if action["kind"] == "submit_candidates":
                action["payload"]["stop_reason"] = "I have enough evidence"
            return response.model_copy(update={"content": json.dumps(action)})
    case = api("load_corpus")()[0]
    result = await api("run_case")(case, tmp_path, mode="specialist", provider=NarrativeStop(api("review_input")(case)))
    assert result["coverage"]["failed"]
    assert result["evaluation_eligible"] is True
    assert result["score"]["true_positive"] == 1


@pytest.mark.asyncio
async def test_legacy_evaluator_no_longer_accepts_any_finding_as_true_positive(tmp_path):
    from pathlib import Path
    from scripts.evaluate_reviews import ContractProbeProvider, evaluate
    class UnrelatedProvider(ContractProbeProvider):
        async def generate_completion(self, request):
            response = await super().generate_completion(request)
            action = json.loads(response.content)
            if action["kind"] == "submit_candidates":
                for candidate in action["payload"]["candidates"]:
                    candidate.update(title="Unrelated style warning", description="Remove an unused import", impact="Style")
            return response.model_copy(update={"content": json.dumps(action)})
    corpus = json.loads(Path("tests/fixtures/canonical-review-eval-v2.json").read_text())
    result = await evaluate(corpus["cases"][:1], tmp_path, provider_factory=UnrelatedProvider)
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (0, 0, 1)
    score = result['results'][0]['candidate_score']
    assert (score['true_positive'], score['false_positive'], score['false_negative']) == (0, 1, 1)


def test_human_tool_review_is_tied_to_actual_operations():
    row = {"status": "completed", "gold": [gold()], "findings": [finding()], "evidence": evidence(), "metrics": {},
           "tool_observations": [{"operation_id": "observed"}]}
    result = api("adjudicate_row")(row, {"findings": {"0": {"defect_id": "empty-input", "evidence_correct": True}},
        "tools": {"observed": {"appropriate": True, "necessary": False}}})
    assert result["metrics"]["tool_selection_quality"] == 1
    assert result["metrics"]["unnecessary_tool_calls"] == 1
    assert result["score"]["semantic_evidence_correctness"] == 1
    with pytest.raises(ValueError, match="operation"):
        api("adjudicate_row")(row, {"tools": {"invented": {"appropriate": True, "necessary": True}}})


def test_cli_requires_explicit_mode_and_refuses_overwriting(tmp_path):
    from scripts.run_agent_evaluation import main
    output = tmp_path / "result.json"
    with pytest.raises(SystemExit):
        main(["--output", str(output)])
    assert not output.exists()
    output.write_text("preserve", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--fixture", "--output", str(output)])
    assert output.read_text() == "preserve"


def test_live_cli_requires_rates_and_explicit_cap_before_dispatch(tmp_path):
    from scripts.run_agent_evaluation import main
    output = tmp_path / "result.json"
    with pytest.raises(SystemExit):
        main(["--live", "--output", str(output)])
    assert not output.exists()


def test_rescore_uses_saved_findings_and_updates_semantic_judgments(tmp_path):
    from scripts.run_agent_evaluation import main
    original, annotations, output = (tmp_path / name for name in ("original.json", "judgments.json", "scored.json"))
    row = {"case_id": "empty-defect", "mode": "full", "specialist": "bug_reliability", "status": "completed",
           "gold": [gold()], "findings": [finding()], "evidence": evidence(), "metrics": {}, "tool_observations": []}
    original.write_text(json.dumps({"mode": "live-model", "complete": True, "results": [row]}))
    annotations.write_text(json.dumps({"empty-defect:full": {"findings": {
        "0": {"defect_id": "empty-input", "evidence_correct": False}}}}))
    assert main(["--rescore", str(original), "--judgments", str(annotations), "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["groups"]["full"]["true_positive"] == 0
    assert result["results"][0]["score"]["semantic_evidence_correctness"] == 0
    assert result["live_model_accuracy"]["full"]["recall"] == 0


@pytest.mark.parametrize("case", api("load_corpus")(), ids=lambda case: case["case_id"])
def test_independent_witness_distinguishes_each_defect_and_repair(case, tmp_path, monkeypatch):
    """Behavioral witnesses audit corpus labels; they are never reviewer input."""
    import shutil
    import sqlite3
    import subprocess
    import sys
    from types import SimpleNamespace
    family = case["family"]
    if family == "offset":
        node = shutil.which("node")
        assert node, "corpus witness requires Node, as does the existing evaluation gate"
        probe = case["files"]["subject.js"] + "\nprocess.exit(offset(1) === 0 ? 0 : 1);"
        result = subprocess.run([node, "-e", probe], cwd=tmp_path, capture_output=True, timeout=10)
        violated = result.returncode == 1
        assert result.returncode in {0, 1}
    else:
        namespace = {}
        path = "test_subject.py" if family == "assertion" else "subject.py"
        exec(compile(case["files"][path], path, "exec"), namespace)
        if family == "empty":
            try:
                violated = namespace["first"]([]) is not None
            except IndexError:
                violated = True
        elif family == "mutation":
            values = [3, 1, 2]
            namespace["ordered"](values)
            violated = values != [3, 1, 2]
        elif family == "assertion":
            monkeypatch.setitem(sys.modules, "subject", SimpleNamespace(add=lambda a, b: -99))
            try:
                namespace["test_add"]()
                violated = True
            except AssertionError:
                violated = False
        elif family == "query":
            with sqlite3.connect(":memory:") as db:
                db.executescript("CREATE TABLE users(id INTEGER, name TEXT); INSERT INTO users VALUES(1, 'alice');")
                violated = namespace["find_user"](db, "' OR 1=1 --") is not None
        else:
            class CountedInt(int):
                comparisons = 0
                __hash__ = int.__hash__
                def __eq__(self, other):
                    type(self).comparisons += 1
                    return super().__eq__(other)
            values = [CountedInt(i) for i in range(100)]
            assert len(namespace["unique"](values)) == 100
            violated = CountedInt.comparisons > 400
    assert violated == bool(case["gold"])


