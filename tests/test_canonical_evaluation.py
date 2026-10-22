"""Quality gates use independent labels and real canonical tool/acceptance paths."""
import asyncio
import importlib
import json
from pathlib import Path


def corpus():
    return json.loads((Path(__file__).parent / "fixtures/canonical-review-eval-v2.json").read_text())


def test_sixty_case_corpus_has_distinct_scenarios_and_balanced_independent_labels():
    cases = corpus()["cases"]
    assert len(cases) >= 60
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert len({json.dumps(case["files"], sort_keys=True) for case in cases}) == len(cases)
    assert sum(case["expected_defect"] for case in cases) == 30
    assert {case["language"] for case in cases} == {"python", "javascript"}


def test_canonical_offline_precision_and_recall_gate(tmp_path):
    api = importlib.import_module("scripts.evaluate_reviews")
    summary = asyncio.run(api.evaluate(corpus()["cases"], tmp_path))
    assert summary["mode"] == "offline-contract-integration"
    assert summary["cases"] >= 60
    # User-selected conservative publication: model judgments remain candidates.
    assert summary["confirmed_precision"] == summary["confirmed_recall"] == 0
    assert summary['passes_quality_gate'] is False
    assert summary['publication_policy_satisfied'] is True
    assert summary['candidate_precision'] >= .9
    assert summary['candidate_recall'] >= .7
    assert summary['passes_candidate_gate'] is True
    assert summary["live_model_accuracy"] is None
    assert summary["failed_jobs"] == 0


def test_silent_reviewer_fails_recall_and_cannot_read_gold_labels(tmp_path):
    api = importlib.import_module("scripts.evaluate_reviews")
    class Silent(api.ContractProbeProvider):
        def __init__(self, public_case):
            assert "expected_defect" not in public_case
            assert "case_id" not in public_case
            super().__init__(public_case, suppress_candidates=True)
    result = asyncio.run(api.evaluate([corpus()["cases"][0]], tmp_path, provider_factory=Silent))
    assert result["confirmed_recall"] == 0
    assert result["passes_quality_gate"] is False


def test_offline_probe_retrieves_paged_command_output_without_losing_a_defect(tmp_path):
    api=importlib.import_module('scripts.evaluate_reviews')
    result=asyncio.run(api.evaluate([corpus()['cases'][42]],tmp_path))
    assert result['results'][0]['candidate_score']['true_positive']==1
    assert result['true_positive']==0
    assert result['failed_jobs']==0
