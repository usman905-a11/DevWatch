"""Captured omissions survive immutable storage and deterministic report rendering."""
import json

import pytest
from fastapi.testclient import TestClient

from tests.test_review_service import ALICE, app, completed


def test_capture_metadata_is_persisted_without_fabricating_inspection(tmp_path):
    with TestClient(app(tmp_path)) as client:
        snapshot = client.post("/api/snapshots", headers=ALICE, json={
            "files": {"service.py": "def first(items):\n    return items[0]\n"},
            "capture_coverage": {"skipped": {"omitted.py": "snapshot_file_limit"},
                                 "failed": {"invalid.py": "invalid_text_source"}, "limitations": ["Bounded client capture"]}})
        assert snapshot.status_code == 201
        identity = client.post("/api/jobs", headers={**ALICE, "Idempotency-Key": "scope"},
                               json={"snapshot_id": snapshot.json()["snapshot_id"]}).json()["job_id"]
        assert completed(client, identity)["status"] == "completed"
        report = client.get(f"/api/jobs/{identity}/report", headers=ALICE).json()
        assert report["coverage"]["skipped"]["omitted.py"] == "snapshot_file_limit"
        assert report["coverage"]["failed"]["invalid.py"] == "invalid_text_source"
        assert report["coverage"]["inspected_files"] == ["service.py"]
        assert "Bounded client capture" in report["coverage"]["limitations"]


def test_capture_metadata_cannot_claim_inspection_and_is_integrity_checked(tmp_path):
    import sqlite3
    with TestClient(app(tmp_path)) as client:
        forged = client.post("/api/snapshots", headers=ALICE, json={"files": {}, "capture_coverage": {"inspected_files": ["fake.py"]}})
        assert forged.status_code == 422
        valid = client.post("/api/snapshots", headers=ALICE, json={"files": {}, "capture_coverage": {"skipped": {"a.py": "omitted"}}})
        assert valid.status_code == 201
        identity = valid.json()["snapshot_id"]
        with sqlite3.connect(tmp_path / "runtime" / "devwatch.sqlite") as db:
            row = db.execute("SELECT manifest FROM snapshots WHERE snapshot_id=?", (identity,)).fetchone()
            record = json.loads(row[0])
            record["capture_coverage"]["skipped"]["a.py"] = "tampered"
            db.execute("UPDATE snapshots SET manifest=? WHERE snapshot_id=?", (json.dumps(record), identity))
            db.commit()
        response = client.post("/api/jobs", headers={**ALICE, "Idempotency-Key": "tampered"}, json={"snapshot_id": identity})
        assert response.status_code == 422
