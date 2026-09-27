"""Versioned offline evaluation contract for the new review workflow."""

import json
from pathlib import Path

from devwatch.tools.static_analyzer import ASTStaticAnalyzerTool


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "review_eval_v1.json"


def load_cases():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["version"] == "review-eval-v1"
    return fixture["cases"]


def score_cases(cases, predicted_titles_by_id):
    """Count exact expected findings; any unmatched prediction is a false positive."""
    true_positives = false_positives = false_negatives = 0
    for case in cases:
        expected = set(case["expected_titles"])
        predicted = set(predicted_titles_by_id.get(case["id"], []))
        true_positives += len(expected & predicted)
        false_positives += len(predicted - expected)
        false_negatives += len(expected - predicted)
    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )
    return {
        "precision": precision,
        "recall": recall,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def test_fixture_is_versioned_mixed_and_diff_shaped():
    cases = load_cases()
    assert len(cases) >= 20
    assert len({case["id"] for case in cases}) == len(cases)
    assert any(case["expected_titles"] for case in cases)
    assert any(not case["expected_titles"] for case in cases)
    for case in cases:
        assert case["before"] != case["after"]
        assert case["file_path"]


def test_offline_scoring_reports_precision_recall_and_rejects_silence():
    cases = load_cases()
    silent = score_cases(cases, {})
    assert silent["precision"] == 0.0
    assert silent["recall"] == 0.0
    assert silent["false_negatives"] > 0

    perfect = score_cases(
        cases, {case["id"]: case["expected_titles"] for case in cases}
    )
    assert perfect["precision"] == 1.0
    assert perfect["recall"] == 1.0

    first_bug = next(case for case in cases if case["expected_titles"])
    imperfect_predictions = {
        case["id"]: case["expected_titles"] for case in cases
    }
    imperfect_predictions[first_bug["id"]] = []
    first_clean = next(case for case in cases if not case["expected_titles"])
    imperfect_predictions[first_clean["id"]] = ["Invented bug"]
    imperfect = score_cases(cases, imperfect_predictions)
    assert imperfect["false_positives"] == 1
    assert imperfect["false_negatives"] == 1
    assert imperfect["precision"] < 1.0
    assert imperfect["recall"] < 1.0


def test_offline_static_baseline_is_measurable_without_live_provider():
    analyzer = ASTStaticAnalyzerTool()
    cases = load_cases()
    predicted = {
        case["id"]: [
            issue.title
            for issue in analyzer.analyze_file(case["file_path"], case["after"])
        ]
        for case in cases
    }
    scores = score_cases(cases, predicted)
    assert scores["true_positives"] > 0
    assert 0.0 <= scores["precision"] <= 1.0
    assert 0.0 <= scores["recall"] <= 1.0
