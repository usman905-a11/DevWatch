"""Immutable eligible Git metadata, without executing repository diff helpers."""
import asyncio
import subprocess

import pytest

from devwatch.review.capture import capture_source
from devwatch.review.contracts import AgentAction, AgentId, ReviewTask
from devwatch.review.repository import RepositoryContext
from devwatch.review.stores import ArtifactStore, RepoCache


def test_capture_keeps_staged_and_unstaged_git_evidence_snapshot_bound(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*argv):
        subprocess.run(["git", "-C", str(root), *argv], check=True, stdout=subprocess.DEVNULL)
    git("init", "-q")
    (root / "service.py").write_text("value = 1\n")
    git("add", "service.py")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Initial fixture")
    (root / "service.py").write_text("value = 2\n")
    git("add", "service.py")
    (root / "service.py").write_text("value = 3\n")
    (root / ".env").write_text("DO-NOT-UPLOAD=secret")
    capture = capture_source(root)
    assert "+value = 2" in capture.git_metadata.diffs["service.py"]["staged"]
    assert "+value = 3" in capture.git_metadata.diffs["service.py"]["unstaged"]
    assert "Initial fixture" in str(capture.git_metadata.history["service.py"])
    artifacts = ArtifactStore(tmp_path / "artifacts")
    snapshot = artifacts.capture(owner="alice", files=capture.files, git_metadata=capture.git_metadata)
    (root / "service.py").write_text("value = 99\n")
    repo = RepositoryContext(artifacts, RepoCache(tmp_path / "cache.sqlite"), snapshot.snapshot_id, owner="alice")
    task = ReviewTask(task_id="bug", agent_id=AgentId.BUG_RELIABILITY, files=["service.py"], focus="Changed value")
    async def scenario():
        evidence = await repo.tools().execute(task, AgentAction(kind="call_tool", tool="git_diff", arguments={"file_path": "service.py"}))
        record = repo.evidence(evidence.evidence_ref)
        assert "+value = 3" in str(record) and "value = 99" not in str(record)
        assert "DO-NOT-UPLOAD" not in str(snapshot.model_dump())
        with pytest.raises(PermissionError):
            artifacts.manifest(snapshot.snapshot_id, owner="bob")
    asyncio.run(scenario())
