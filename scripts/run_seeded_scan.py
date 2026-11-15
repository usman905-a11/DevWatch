"""Run one baseline DevWatch scan against tests/fixtures/seeded_repo."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from devwatch.providers.openai_adapter import OpenAIProviderAdapter
from dotenv import load_dotenv
from devwatch.review.contracts import ModelTier
from devwatch.review.jobs import DurableJobManager, JobStore
from devwatch.review.service import ServiceSettings
from devwatch.review.stores import ArtifactStore, StoreLayout
from devwatch.review.workflow import CanonicalReviewExecutor


DEFAULT_REPO = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "seeded_repo"
DEFAULT_MANIFEST = DEFAULT_REPO / "manifest.json"
FINDING_BUCKETS = ("confirmed_defects", "uncertain_high_impact_candidates", "advisories")


def load_seeded_manifest(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    issues = data.get("issues", [])
    if not isinstance(issues, list) or not issues:
        raise ValueError("Seeded manifest must define a non-empty issues list")
    return issues


def _findings_with_agents(report: dict[str, Any]) -> list[dict[str, Any]]:
    provenance = (report.get("verification_audit") or {}).get("provenance") or {}
    collected: list[dict[str, Any]] = []
    for bucket in FINDING_BUCKETS:
        for finding in report.get(bucket, []):
            finding_id = finding.get("finding_id", "")
            agent_id = (provenance.get(finding_id) or {}).get("agent_id") or "unknown"
            collected.append({"bucket": bucket, "agent_id": agent_id, "finding": finding})
    return collected


def _overlaps_issue(finding: dict[str, Any], issue: dict[str, Any]) -> bool:
    location = finding.get("location") or {}
    if location.get("file_path") != issue.get("file"):
        return False
    f_start = int(location.get("start_line", 0))
    f_end = int(location.get("end_line", f_start))
    i_start = int(issue["line"])
    i_end = int(issue.get("end_line", i_start))
    return f_start <= i_end and f_end >= i_start


def match_seeded_issues(manifest_issues: list[dict[str, Any]], report: dict[str, Any]) -> dict[str, Any]:
    reported = _findings_with_agents(report)
    matched_finding_indexes: set[int] = set()
    found: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []

    for issue in manifest_issues:
        hits = [
            (idx, item)
            for idx, item in enumerate(reported)
            if _overlaps_issue(item["finding"], issue)
        ]
        if hits:
            for idx, _ in hits:
                matched_finding_indexes.add(idx)
            agents = sorted({item["agent_id"] for _, item in hits})
            found.append({
                "id": issue["id"],
                "file": issue["file"],
                "line": issue["line"],
                "category": issue["category"],
                "title": issue["title"],
                "found_by": agents,
                "matched_titles": [item["finding"].get("title", "") for _, item in hits],
            })
        else:
            missed.append({
                "id": issue["id"],
                "file": issue["file"],
                "line": issue["line"],
                "category": issue["category"],
                "title": issue["title"],
            })

    false_positives = []
    for idx, item in enumerate(reported):
        if idx in matched_finding_indexes:
            continue
        finding = item["finding"]
        loc = finding.get("location") or {}
        false_positives.append({
            "finding_id": finding.get("finding_id"),
            "agent_id": item["agent_id"],
            "bucket": item["bucket"],
            "file": loc.get("file_path"),
            "start_line": loc.get("start_line"),
            "end_line": loc.get("end_line"),
            "category": finding.get("category"),
            "title": finding.get("title"),
        })

    audit = report.get("verification_audit") or {}
    decisions = audit.get("decisions") or []
    rejected_count = sum(1 for item in decisions if item.get("verdict") == "rejected")

    return {
        "seeded_total": len(manifest_issues),
        "found_count": len(found),
        "missed_count": len(missed),
        "false_positive_count": len(false_positives),
        "rejected_count": rejected_count,
        "found": found,
        "missed": missed,
        "false_positives": false_positives,
        "report_summary": report.get("summary", ""),
        "limitations": report.get("limitations", []),
        "coverage": report.get("coverage", {}),
    }


def format_baseline_summary(summary: dict[str, Any]) -> str:
    coverage = summary.get("coverage") or {}
    failed = coverage.get("failed") or {}
    inspected = coverage.get("inspected_files") or []
    lines = [
        f"Seeded baseline: {summary['found_count']}/{summary['seeded_total']} found, "
        f"{summary['missed_count']} missed, {summary['false_positive_count']} false positive(s).",
    ]
    if "total_tokens" in summary or inspected or failed or summary.get("rejected_count"):
        tokens = summary.get("total_tokens", "n/a")
        rejected = summary.get("rejected_count", 0)
        lines.append(
            f"Run stats: status={summary.get('job_status', 'n/a')}, tokens={tokens}, "
            f"inspected_files={len(inspected)}, rejected_candidates={rejected}, failed={list(failed.keys()) or 'none'}"
        )
    if failed:
        for stage, reason in failed.items():
            lines.append(f"  failure[{stage}]: {reason}")
    if summary.get("limitations"):
        for note in summary["limitations"]:
            lines.append(f"  limitation: {note}")
    lines.extend([
        "",
        "Found:",
    ])
    if not summary["found"]:
        lines.append("  (none)")
    for item in summary["found"]:
        lines.append(
            f"  - [{item['id']}] {item['file']}:{item['line']} ({item['category']}) "
            f"by {', '.join(item['found_by'])} :: {item['title']}"
        )
    lines.append("")
    lines.append("Missed:")
    if not summary["missed"]:
        lines.append("  (none)")
    for item in summary["missed"]:
        lines.append(f"  - [{item['id']}] {item['file']}:{item['line']} ({item['category']}) :: {item['title']}")
    lines.append("")
    lines.append("False positives:")
    if not summary["false_positives"]:
        lines.append("  (none)")
    for item in summary["false_positives"]:
        lines.append(
            f"  - {item['file']}:{item['start_line']}-{item['end_line']} "
            f"({item['category']}, {item['bucket']}) by {item['agent_id']} :: {item['title']}"
        )
    return "\n".join(lines)


async def run_seeded_scan(
    repo_path: Path,
    manifest_path: Path,
    *,
    runtime_dir: Path | None = None,
    provider: Any | None = None,
    models: dict[Any, str] | None = None,
) -> dict[str, Any]:
    if provider is None:
        load_dotenv(REPO_ROOT / ".env", override=False)
        settings = ServiceSettings.from_env()
        default_provider = "gemini" if settings.models[ModelTier.SMALL].startswith("gemini-") else "openai"
        provider_name = (os.getenv("DEVWATCH_PROVIDER") or default_provider).strip().lower() or default_provider
        provider = OpenAIProviderAdapter(provider_name=provider_name, max_concurrency=3)
        if not provider.is_available():
            raise RuntimeError(
                "No configured LLM provider credentials found. Set DEVWATCH_MODEL and a matching "
                "API key (OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY) before running."
            )
        resolved_models = settings.models
    else:
        resolved_models = models or ServiceSettings.from_env().models
    issues = load_seeded_manifest(manifest_path)

    async def _execute(root: Path) -> dict[str, Any]:
        layout = StoreLayout(root)
        artifacts = ArtifactStore(layout.app_db)
        jobs = JobStore(layout.app_db)
        executor = CanonicalReviewExecutor(layout, artifacts, jobs, provider, models=resolved_models)
        manager = DurableJobManager(jobs, executor)
        try:
            job = await manager.submit(
                owner="baseline",
                request={"workspace_path": str(repo_path.resolve())},
                idempotency_key="seeded-baseline",
            )
            finished = await manager.wait(job.job_id, owner="baseline")
        finally:
            await manager.close()
        if finished.status != "completed" or not finished.result or "json" not in finished.result:
            raise RuntimeError(f"Seeded scan ended with status={finished.status!r}: {finished.error}")
        report = json.loads(finished.result["json"])
        summary = match_seeded_issues(issues, report)
        summary["job_status"] = finished.status
        summary["total_tokens"] = finished.ledger.total_tokens
        return summary

    if runtime_dir is not None:
        return await _execute(runtime_dir)
    with tempfile.TemporaryDirectory(prefix="devwatch-seeded-") as tmp:
        return await _execute(Path(tmp))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one baseline DevWatch scan on tests/fixtures/seeded_repo.")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="Print JSON summary instead of formatted text.")
    args = parser.parse_args()

    summary = asyncio.run(run_seeded_scan(args.repo, args.manifest, runtime_dir=args.runtime_dir))
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(format_baseline_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
