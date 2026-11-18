"""Phase 4 TDD backend test: owner-isolated GET /api/jobs history listing."""

from pathlib import Path
from fastapi.testclient import TestClient

from backend.providers.base import LLMResponse, LLMUsage
from backend.review.contracts import ModelTier
from backend.review.service import ServiceSettings, create_app


class QuickProvider:
    async def generate_completion(self, request):
        import json

        data = json.loads(request.prompt)
        role = data["task"]["agent_id"]
        if role == "planner":
            action = {
                "kind": "submit_plan",
                "payload": {
                    "selected_agents": [],
                    "priority_files": [],
                    "priority_symbols": [],
                    "risk_areas": [],
                    "review_tasks": [],
                    "review_strategy": "Quick",
                    "coverage_expectations": [],
                },
            }
        elif data["phase"] == "verification":
            action = {"kind": "submit_verification", "payload": {"decisions": []}}
        else:
            action = {"kind": "submit_synthesis", "payload": {"summary": "Empty", "limitations": []}}
        return LLMResponse(
            finish_reason="stop",
            content=json.dumps(action),
            provider="scripted",
            model=request.model,
            latency_ms=0,
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def test_list_jobs_returns_owner_scoped_jobs_ordered_newest_first_with_limit(tmp_path: Path):
    app = create_app(
        settings=ServiceSettings(
            runtime_root=tmp_path / "runtime",
            models={t: t.value for t in ModelTier},
            api_keys=frozenset({"alice-key", "bob-key"}),
        ),
        provider=QuickProvider(),
    )
    with TestClient(app) as client:
        alice = {"X-API-Key": "alice-key"}
        bob = {"X-API-Key": "bob-key"}

        snap_a = client.post("/api/snapshots", headers=alice, json={"files": {"a.py": "x = 1\n"}}).json()["snapshot_id"]
        snap_b = client.post("/api/snapshots", headers=bob, json={"files": {"b.py": "y = 2\n"}}).json()["snapshot_id"]

        j1 = client.post(
            "/api/jobs",
            headers={**alice, "Idempotency-Key": "a-1"},
            json={"snapshot_id": snap_a},
        ).json()["job_id"]
        j2 = client.post(
            "/api/jobs",
            headers={**alice, "Idempotency-Key": "a-2"},
            json={"snapshot_id": snap_a},
        ).json()["job_id"]
        jb = client.post(
            "/api/jobs",
            headers={**bob, "Idempotency-Key": "b-1"},
            json={"snapshot_id": snap_b},
        ).json()["job_id"]

        alice_list = client.get("/api/jobs", headers=alice)
        assert alice_list.status_code == 200
        alice_jobs = alice_list.json()["jobs"]
        assert [j["job_id"] for j in alice_jobs] == [j2, j1]
        assert all("owner" not in j for j in alice_jobs)

        limited = client.get("/api/jobs?limit=1", headers=alice)
        assert limited.status_code == 200
        assert [j["job_id"] for j in limited.json()["jobs"]] == [j2]

        bob_list = client.get("/api/jobs", headers=bob)
        assert bob_list.status_code == 200
        assert [j["job_id"] for j in bob_list.json()["jobs"]] == [jb]

        import time
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            cur = client.get(f"/api/jobs/{j2}", headers=alice).json()
            if cur["status"] == "completed":
                break
            time.sleep(0.05)
        completed_list = client.get("/api/jobs", headers=alice).json()["jobs"]
        j2_view = next(item for item in completed_list if item["job_id"] == j2)
        assert isinstance(j2_view["summary_preview"], str)
        assert "0 confirmed defect" in j2_view["summary_preview"]
        assert j2_view["finding_counts"] == {"defects": 0, "uncertain": 0, "advisories": 0}

