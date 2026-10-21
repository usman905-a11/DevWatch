import json

from fastapi.testclient import TestClient

from tests.test_review_service import ALICE, app, completed


def test_empty_change_selection_finishes_through_gate_without_model_calls(tmp_path):
    from tests.test_canonical_workflow import ReviewProvider
    provider = ReviewProvider()
    with TestClient(app(tmp_path, provider=provider)) as client:
        snapshot = client.post("/api/snapshots", headers=ALICE, json={"files": {"service.py": "pass\n"}}).json()
        job = client.post("/api/jobs", headers={**ALICE, "Idempotency-Key": "empty"}, json={
            "snapshot_id": snapshot["snapshot_id"], "changed_files": []}).json()
        done = completed(client, job["job_id"])
        assert done["status"] == "completed"
        report = client.get(f"/api/jobs/{job['job_id']}/report?format=json", headers=ALICE).json()
        assert not provider.requests
        assert not report["coverage"]["inspected_files"]
        assert not report["confirmed_defects"]
        assert '0 captured source file(s) inspected' in report['summary']
        assert 'Empty change selection; no AI investigation requested.' in report['limitations']
