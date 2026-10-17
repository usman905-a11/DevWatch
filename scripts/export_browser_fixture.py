"""Create offline browser fixtures from the real canonical ASGI graph/stores."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from devwatch.review.jobs import EventPayload, PersistedEvent
from devwatch.review.contracts import ReportDraft, ReviewTask
from tests.test_review_service import ALICE, app, completed


def main():
    with TemporaryDirectory() as directory:
        with TestClient(app(Path(directory))) as client:
            files = {"service.py": "def first(items):\n    return items[0]\n", "😀.py": "pass\n", "\ue000.py": "pass\n"}
            omissions = {"skipped": {"dist/generated.js": "excluded_source"}, "failed": {}, "limitations": ["Offline test fixture"]}
            snapshot = client.post("/api/snapshots", headers=ALICE, json={"files": files, "capture_coverage": omissions}).json()
            job = client.post("/api/jobs", headers={**ALICE, "Idempotency-Key": "browser-fixture"},
                              json={"snapshot_id": snapshot["snapshot_id"]}).json()
            result = completed(client, job["job_id"])
            assert result["status"] == "completed"
            prefix = f"/api/jobs/{job['job_id']}"
            report = client.get(prefix + "/report", headers=ALICE).json()
            events = client.get(prefix + "/events?limit=1000", headers=ALICE).json()["events"]
            source = client.get(prefix + "/source?file_path=service.py&start_line=1&end_line=2", headers=ALICE).json()
            unicode_event = PersistedEvent(event_id="unicode-fixture", job_id=job["job_id"], sequence=1,
                kind="agent_started", payload=EventPayload(agent_id="logic_correctness", task_id="任务." + "𠀀" * 120), timestamp=1)
            failed_report = ReportDraft.model_validate(report)
            for task_id in ("security.", "con"):
                task = ReviewTask(task_id=task_id, agent_id="architecture_security", files=["service.py"], focus="Inspect configuration")
                failed_report.coverage.failed[task.task_id] = "tool_unavailable"
            fixture = {"files": files, "snapshot": snapshot, "job": result, "report": report, "events": events,
                       "failed_task_report": failed_report.model_dump(mode="json"),
                       "source": source, "unicode_event": unicode_event.model_dump(mode="json")}
    destination = Path(__file__).resolve().parents[1] / "frontend/src/__tests__/fixtures/canonical-wire.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(fixture, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
