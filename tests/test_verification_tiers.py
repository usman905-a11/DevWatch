"""Phase 1 verification policy tests: Confirmed / Advisory / Potential / Rejected distinction & severity."""
import asyncio
import json

import pytest

from backend.providers.base import LLMResponse, LLMUsage
from backend.review.contracts import FindingCandidate, ModelTier
from backend.review.jobs import DurableJobManager, JobStore
from backend.review.stores import ArtifactStore, StoreLayout
from backend.review.workflow import CanonicalReviewExecutor
from tests.test_canonical_workflow import stores
from tests.test_control_agents import plan_payload
from tests.verification_fixtures import reviewed


class ClassificationProvider:
    """Two-pass scripted provider exercising Confirmed, Advisory, Potential, and Rejected outcomes."""

    def __init__(self, *, verdict: str, second_verdict: str | None = None, severity: str = "high"):
        self.verdict = verdict
        self.second_verdict = second_verdict or verdict
        self.severity = severity
        self.verify_calls = 0

    async def generate_completion(self, request):
        data = json.loads(request.prompt)
        role = data["task"]["agent_id"]
        phase = data["phase"]
        evidence_refs = [page["evidence_ref"] for page in data["selected_context"].get("evidence", [])]
        if role == "planner":
            action = {"kind": "submit_plan", "payload": plan_payload()}
        elif role == "logic_correctness":
            if not data["private_state"]["evidence_refs"]:
                action = {"kind": "call_tool", "tool": "read_file", "arguments": {"file_path": "service.py"}}
            else:
                candidate = {
                    "category": "logic",
                    "kind": "advisory" if self.verdict == "advisory" else "defect",
                    "severity": self.severity,
                    "title": "Empty input raises",
                    "description": "items[0] indexes without checking emptiness.",
                    "impact": "Raises IndexError on empty input.",
                    "confidence": 0.9,
                    "evidence_refs": data["private_state"]["evidence_refs"],
                    "location": {
                        "snapshot_id": data["selected_context"]["snapshot_id"],
                        "file_path": "service.py",
                        "start_line": 2,
                        "end_line": 2,
                    },
                    "remediation": "Return None when items is empty.",
                }
                action = {
                    "kind": "submit_candidates",
                    "payload": {
                        "task_id": "logic-1",
                        "agent_id": role,
                        "candidates": [candidate],
                        "coverage": {},
                        "stop_reason": "evidence_complete",
                    },
                }
        else:
            assert phase == "verification"
            self.verify_calls += 1
            chosen = self.verdict if self.verify_calls == 1 else self.second_verdict
            statuses = {"impact": "uncertain"} if chosen == "uncertain" else ({"impact": "unsupported"} if chosen == "rejected" else {})
            decisions = [
                {
                    "finding_id": identity,
                    "verdict": chosen,
                    "confidence": 0.65 if chosen == "uncertain" else 0.92,
                    "rationale": f"Verified as {chosen} against inspected source",
                    "evidence_refs": candidate["evidence_refs"],
                    "causal_review": reviewed(candidate, candidate["evidence_refs"], statuses=statuses),
                }
                for identity, candidate in data["candidates"].items()
            ]
            action = {"kind": "submit_verification", "payload": {"decisions": decisions}}
        action["inspected_evidence"] = evidence_refs
        return LLMResponse(
            finish_reason="stop",
            content=json.dumps(action),
            provider="scripted",
            model=request.model,
            latency_ms=0,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


@pytest.mark.asyncio
async def test_confirmed_non_arithmetic_finding_publishes_to_confirmed_defects_with_severity(tmp_path):
    layout, artifacts, snapshot, jobs = stores(tmp_path)
    executor = CanonicalReviewExecutor(
        layout, artifacts, jobs, ClassificationProvider(verdict="confirmed", severity="critical"),
        models={t: t.value for t in ModelTier},
    )
    manager = DurableJobManager(jobs, executor)
    job = await manager.submit(owner="alice", request={"snapshot_id": snapshot.snapshot_id}, idempotency_key="v-confirmed")
    done = await manager.wait(job.job_id, owner="alice")
    await manager.close()
    assert done.status == "completed"
    report = json.loads(done.result["json"])
    assert len(report["confirmed_defects"]) == 1
    assert report["confirmed_defects"][0]["severity"] == "critical"
    assert report["confirmed_defects"][0]["confidence"] == pytest.approx(0.92)
    assert report["uncertain_high_impact_candidates"] == []
    assert report["advisories"] == []


@pytest.mark.asyncio
async def test_advisory_rejected_and_disagreed_potential_findings_route_to_proper_buckets(tmp_path):
    # Agreed advisory -> advisories
    layout1, artifacts1, snap1, jobs1 = stores(tmp_path / "adv")
    ex1 = CanonicalReviewExecutor(
        layout1, artifacts1, jobs1, ClassificationProvider(verdict="advisory", severity="low"),
        models={t: t.value for t in ModelTier},
    )
    m1 = DurableJobManager(jobs1, ex1)
    j1 = await m1.submit(owner="alice", request={"snapshot_id": snap1.snapshot_id}, idempotency_key="v-adv")
    r1 = json.loads((await m1.wait(j1.job_id, owner="alice")).result["json"])
    await m1.close()
    assert len(r1["advisories"]) == 1
    assert r1["advisories"][0]["severity"] == "low"
    assert r1["confirmed_defects"] == []

    # Agreed rejected -> excluded from active buckets, kept in audit
    layout2, artifacts2, snap2, jobs2 = stores(tmp_path / "rej")
    ex2 = CanonicalReviewExecutor(
        layout2, artifacts2, jobs2, ClassificationProvider(verdict="rejected"),
        models={t: t.value for t in ModelTier},
    )
    m2 = DurableJobManager(jobs2, ex2)
    j2 = await m2.submit(owner="alice", request={"snapshot_id": snap2.snapshot_id}, idempotency_key="v-rej")
    r2 = json.loads((await m2.wait(j2.job_id, owner="alice")).result["json"])
    await m2.close()
    assert r2["confirmed_defects"] == []
    assert r2["uncertain_high_impact_candidates"] == []
    assert r2["advisories"] == []
    assert r2["verification_audit"]["decisions"][0]["verdict"] == "rejected"

    # Pass 1 confirmed vs Pass 2 rejected disagreement -> downgraded to Potential (uncertain <= 0.5)
    layout3, artifacts3, snap3, jobs3 = stores(tmp_path / "dis")
    ex3 = CanonicalReviewExecutor(
        layout3, artifacts3, jobs3, ClassificationProvider(verdict="confirmed", second_verdict="rejected"),
        models={t: t.value for t in ModelTier},
    )
    m3 = DurableJobManager(jobs3, ex3)
    j3 = await m3.submit(owner="alice", request={"snapshot_id": snap3.snapshot_id}, idempotency_key="v-dis")
    r3 = json.loads((await m3.wait(j3.job_id, owner="alice")).result["json"])
    await m3.close()
    assert r3["confirmed_defects"] == []
    assert len(r3["uncertain_high_impact_candidates"]) == 1
    assert r3["uncertain_high_impact_candidates"][0]["confidence"] <= 0.5

