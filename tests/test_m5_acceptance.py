"""Final report-only and integrated offline acceptance gates."""

import json
import subprocess
from pathlib import Path

import pytest

from devwatch.operations.review_operations import ReviewOperations
from devwatch.review.engine import ReviewEngine


FIXTURE = Path(__file__).parent / "fixtures" / "review_eval_v1.json"


class EmptyAgent:
    async def execute(self, context):
        return []


def _git(repo, *args):
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )


def test_review_operations_does_not_expose_mutation_methods():
    for method in (
        "apply_quick_fix", "propose_remediation_fix",
        "apply_remediation_proposal",
    ):
        assert not hasattr(ReviewOperations, method)



def test_scanner_has_no_source_write_interface():
    from devwatch.scanner import CodebaseScanner

    assert not hasattr(CodebaseScanner, "write_file")


@pytest.mark.asyncio
async def test_integrated_changed_repo_precision_and_recall(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    assert fixture["version"] == "review-eval-v1"
    assert len(cases) >= 20

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    for case in cases:
        path = repo / case["file_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(case["before"], encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo, "-c", "user.name=DevWatch Test", "-c",
        "user.email=devwatch@example.invalid", "commit", "-m", "baseline",
    )
    for case in cases:
        (repo / case["file_path"]).write_text(case["after"], encoding="utf-8")

    engine = ReviewEngine(
        planner=EmptyAgent(),
        specialists={},
        verifier=EmptyAgent(),
        runs_dir=tmp_path / "runs",
        run_commands=False,
    )
    report = await engine.review_repository(str(repo))
    assert report.metrics["partial"] is False
    predicted = {}
    for issue in report.issues:
        predicted.setdefault(issue.file_path, set()).add(issue.title)

    true_positives = false_positives = false_negatives = 0
    for case in cases:
        expected = set(case["expected_titles"])
        actual = predicted.get(case["file_path"], set())
        true_positives += len(expected & actual)
        false_positives += len(actual - expected)
        false_negatives += len(expected - actual)
    precision = true_positives / (true_positives + false_positives) if true_positives + false_positives else 0.0
    recall = true_positives / (true_positives + false_negatives) if true_positives + false_negatives else 0.0

    print(
        f"Integrated offline evaluation: {len(cases)} cases, "
        f"precision={precision:.1%}, recall={recall:.1%}, "
        f"TP={true_positives}, FP={false_positives}, FN={false_negatives}"
    )
    assert precision >= 0.90, (precision, true_positives, false_positives)
    assert recall >= 0.70, (recall, true_positives, false_negatives)
